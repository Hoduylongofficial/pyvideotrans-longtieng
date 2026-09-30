# OmniVoice 远程配音：调用部署在 Modal GPU 上的服务（modal_tts/omnivoice_modal.py）
# params.json: omnivoice_modal_url / omnivoice_modal_key 已设置时，OmniVoice 渠道不再本地运行
# 可选固定参考音色：omnivoice_ref_wav + omnivoice_ref_text（空则服务端用 Whisper 自动识别）
#
# 预生成仓库：环境变量 PYVIDEOTRANS_OMNIVOICE_STORE 指向一个目录时，合成结果按
# (语言, 参考音色, 文本) 存成 FLAC。dub_all 先用 prefetch() 以高并发把所有语言的配音
# 一次性生成进仓库（GPU 连续满载、冷启动少），之后各语言渲染时直接命中，不再调用 Modal。
import base64
import hashlib
import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from videotrans.configure.config import logger, params, ROOT_DIR

BATCH = 32          # 每次请求的句数（服务端 GPU 一次批量 16 句）
SR = 24000
STORE_ENV = 'PYVIDEOTRANS_OMNIVOICE_STORE'


def remote_configured() -> bool:
    return bool(str(params.get('omnivoice_modal_url', '')).strip() and str(params.get('omnivoice_modal_key', '')).strip())


VOICE_ENV = 'PYVIDEOTRANS_OMNIVOICE_VOICE'
# 本地口音音色：用 voice design 生成一次该语言的男声参考音频，之后所有句子都克隆它，
# 保证整段视频（以及以后的视频）音色一致；不克隆则 OmniVoice 每句随机挑音色。
NATIVE_INSTRUCT = 'male, middle-aged'
NATIVE_DIR = Path(ROOT_DIR) / 'f5-tts' / 'omnivoice_native'


def native_voice(language_voice: str = None) -> bool:
    """该语言用 OmniVoice 自带的本地口音音色（不参考任何声音）。

    英语参考音色会把英语口音带进部分语言（实测马来语、菲律宾语明显变差），
    dub_all 按语言设置 "omnivoice_voice": "native"，通过环境变量传给 cli 子进程。
    """
    v = language_voice if language_voice is not None else os.environ.get(VOICE_ENV, '')
    return str(v).strip().lower() == 'native'


def _native_sample(language: str, texts: list) -> str:
    """参考文本：尽量纯本语言（少拉丁字母/品牌名）、完整的句子，拼到约 6 秒。

    参考音频太短（<4 秒）或满是英文品牌名时，克隆出的短句容易读坏（实测日语 3 秒参考：
    「1つ目：監視。」只读出「ん」）。
    """
    import re
    cjk = language.split('-')[0] in ('ja', 'zh', 'ko', 'th')
    target = 32 if cjk else 90  # ~6 秒
    cands = []
    for t in dict.fromkeys(x.strip() for x in texts if x.strip()):
        latin = len(re.findall(r'[A-Za-z]', t)) if language.split('-')[0] not in ('en',) else 0
        latin_ratio = latin / max(1, len(t))
        if latin_ratio > 0.2 or not re.search(r'[.!?。！？]$', t):
            continue  # nhiều chữ Latin hoặc câu dở dang
        cands.append(t)
    if not cands:
        cands = [x.strip() for x in texts if x.strip()] or ['OK']
    cands.sort(key=len, reverse=True)
    sample = ''
    for t in cands:
        sample = (sample + (' ' if not cjk and sample else '') + t) if sample else t
        if len(sample) >= target:
            break
    return sample


def native_ref(language: str, texts: list, url: str, key: str) -> tuple:
    """该语言的本地口音参考音频 (wav 路径, 文本)，没有则在 Modal 上用 voice design 生成一次并保存"""
    import numpy as np
    import soundfile as sf
    path = NATIVE_DIR / f'{language}.wav'
    txt = path.with_suffix('.txt')
    if path.is_file() and txt.is_file():
        return str(path), txt.read_text(encoding='utf-8').strip()
    sample = _native_sample(language, texts)
    for _ in range(3):
        data = _post(url, key, {'items': [{'text': sample, 'language': language, 'instruct': NATIVE_INSTRUCT}]})
        raw = base64.b64decode(data['audios'][0])
        if _valid_audio(raw):
            wav, sr = sf.read(io.BytesIO(raw), dtype='float32')
            NATIVE_DIR.mkdir(parents=True, exist_ok=True)
            sf.write(str(path), np.asarray(wav, dtype=np.float32), sr)
            txt.write_text(sample, encoding='utf-8')
            logger.debug(f'OmniVoice: tạo giọng mẫu bản xứ {language}: {path}')
            return str(path), sample
    raise RuntimeError(f'OmniVoice: không tạo được giọng mẫu bản xứ cho {language}')


def fixed_ref():
    """固定参考音色 (wav 路径, 文本)；未设置则返回 None，表示逐句克隆原视频声音"""
    wav = str(params.get('omnivoice_ref_wav', '') or '').strip()
    if not wav:
        return None
    p = Path(wav) if Path(wav).is_absolute() else Path(ROOT_DIR) / wav
    if not p.is_file():
        raise FileNotFoundError(f'OmniVoice: không thấy file giọng mẫu {p}')
    return str(p), str(params.get('omnivoice_ref_text', '') or '').strip()


def _encode_ref(path: str) -> str:
    """参考音频 -> 24kHz 单声道 FLAC base64，减少上传体积"""
    import numpy as np
    import soundfile as sf
    wav, sr = sf.read(path, dtype='float32', always_2d=True)
    wav = wav.mean(axis=1)
    if sr != SR:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(sr, SR)
        wav = resample_poly(wav, SR // g, sr // g).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, wav, SR, format='FLAC', subtype='PCM_16')
    return base64.b64encode(buf.getvalue()).decode()


def _ref_id(path: str, text: str) -> str:
    return hashlib.md5(Path(path).read_bytes() + b'|' + text.encode()).hexdigest()


def _store_file(store: Path, language: str, ref_id: str, text: str) -> Path:
    return store / f'{hashlib.md5(f"{language}|{ref_id}|{text}".encode()).hexdigest()}.flac'


def _valid_audio(raw: bytes) -> bool:
    """Âm thanh đọc được và không rỗng (câu rất ngắn đôi khi ra 0 byte)."""
    if not raw:
        return False
    try:
        import soundfile as sf
        return sf.info(io.BytesIO(raw)).frames > SR * 0.2
    except Exception:  # noqa: BLE001
        return False


def _store_dir():
    d = os.environ.get(STORE_ENV, '').strip()
    return Path(d) if d else None


def _post(url: str, key: str, body: dict, attempts: int = 3) -> dict:
    last = None
    for n in range(attempts):
        try:
            # Chờ lâu: khi gửi nhiều lượt cùng lúc mà Modal chưa cấp đủ GPU, lượt phải xếp hàng
            # (thời gian xếp hàng không tính tiền). Hết giờ mà gửi lại thì GPU làm lại -> tốn gấp đôi.
            r = requests.post(url.rstrip('/') + '/tts', json=body, timeout=1800,
                              headers={'Authorization': f'Bearer {key}'})
            if r.status_code == 401:
                raise PermissionError('OmniVoice Modal: sai key (omnivoice_modal_key). Nhập lại bằng DOI_TTS.bat mục 2.')
            r.raise_for_status()
            return r.json()
        except PermissionError:
            raise
        except Exception as e:  # noqa: BLE001 - mạng chập chờn / GPU đang khởi động: thử lại
            last = e
            logger.warning(f'OmniVoice Modal lỗi lần {n + 1}/{attempts}: {e}')
            time.sleep(5 * (n + 1))
    raise RuntimeError(f'OmniVoice Modal không phản hồi: {last}')


def synthesize_remote(queue_tts: list, language: str, signal=None, is_exit=None) -> tuple:
    """把 queue_tts 发给 Modal 合成，结果写到 item['filename'] + '-24k.wav'。返回 (成功数, 失败数)"""
    import soundfile as sf
    from videotrans.util.help_misc import vail_file
    from videotrans.util.help_role import get_f5tts_role

    url, key = str(params['omnivoice_modal_url']).strip(), str(params['omnivoice_modal_key']).strip()
    native = native_voice()
    fixed = native_ref(language, [it.get('text', '') for it in queue_tts], url, key) if native else fixed_ref()
    roledict = get_f5tts_role()
    store = _store_dir()
    todo = [it for it in queue_tts if it.get('text', '').strip() and not vail_file(it['filename'])]
    ok = len(queue_tts) - len(todo)
    err = 0

    def ref_of(it):
        if fixed:
            return fixed
        if it.get('role') == 'clone':
            return it.get('ref_wav', ''), it.get('ref_text', '')
        # 角色为 f5-tts 文件夹内的音频
        role = it.get('role', '')
        info = roledict.get(role)
        return f'{ROOT_DIR}/f5-tts/{role}', info.get('ref_text', '') if isinstance(info, dict) else ''

    def save(it, flac_bytes: bytes):
        wav, sr = sf.read(io.BytesIO(flac_bytes), dtype='float32')
        sf.write(it['filename'] + '-24k.wav', wav, sr)

    ref_ids = {}

    def rid_of(it):
        path, text = ref_of(it)
        if path and Path(path).is_file():
            return ref_ids.setdefault((path, text), _ref_id(path, text))
        return None

    # 1) 先从预生成仓库取
    if store:
        rest = []
        for it in todo:
            rid = rid_of(it)
            if rid:
                f = _store_file(store, language, rid, it['text'])
                if f.is_file():
                    raw = f.read_bytes()
                    if _valid_audio(raw):
                        save(it, raw)
                        ok += 1
                        continue
                    f.unlink(missing_ok=True)  # file hỏng/rỗng: xoá, đọc lại qua Modal
            rest.append(it)
        if len(todo) != len(rest):
            logger.debug(f'OmniVoice: {len(todo) - len(rest)} câu lấy từ kho tạo sẵn, {len(rest)} câu gọi Modal')
        todo = rest

    # 2) 剩下的调用 Modal
    encoded = {}  # path -> base64，固定音色只编码一次
    for start in range(0, len(todo), BATCH):
        if is_exit and is_exit():
            break
        chunk = todo[start:start + BATCH]
        ids, items = {}, []
        for it in chunk:
            path, text = ref_of(it)
            item = {'text': it['text'], 'language': language}
            if path and Path(path).is_file():
                item['ref'] = ids.setdefault((path, text), f'r{len(ids)}')
            items.append(item)
        missing = [p for p, _ in ids if p not in encoded]
        with ThreadPoolExecutor(max_workers=4) as pool:
            encoded.update(zip(missing, pool.map(_encode_ref, missing)))
        refs = {rid: {'audio': encoded[path], 'text': text} for (path, text), rid in ids.items()}
        if signal:
            signal(text=f'OmniVoice (GPU Modal) {start + 1}-{start + len(chunk)}/{len(todo)}')
        data = _post(url, key, {'refs': refs, 'items': items})
        for it, audio in zip(chunk, data.get('audios', [])):
            try:
                raw = base64.b64decode(audio)
                if not _valid_audio(raw):
                    raise ValueError('Modal trả về âm thanh rỗng')
                save(it, raw)
                rid = rid_of(it) if store else None
                if rid:
                    store.mkdir(parents=True, exist_ok=True)
                    _store_file(store, language, rid, it['text']).write_bytes(raw)
                ok += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f'OmniVoice Modal: câu lỗi {it.get("line")}: {e}')
                err += 1
        logger.debug(f'OmniVoice Modal: {len(chunk)} câu, GPU {data.get("seconds")}s')
    return ok, err


def prefetch(store: Path, jobs: dict, parallel: int = 8, log=print, native: set = frozenset()) -> dict:
    """固定参考音色下，把 {语言: [文本,...]} 全部预先合成进仓库；native 中的语言用本地口音音色。

    所有语言的分块放进同一个线程池，保持 parallel 个请求同时在 Modal 上跑（每个请求一个 GPU 容器），
    GPU 连续满载后一起空闲关机，比逐语言边合成边渲染少很多冷启动和空等。返回 {语言: (完成, 失败)}。
    """
    fixed = fixed_ref()
    if not fixed:
        return {}
    url, key = str(params['omnivoice_modal_url']).strip(), str(params['omnivoice_modal_key']).strip()
    store.mkdir(parents=True, exist_ok=True)
    # 每种语言一个参考音色：默认固定参考音色，native 语言用本地口音参考音频
    lang_ref = {lang: (native_ref(lang, jobs[lang], url, key) if lang in native else fixed) for lang in jobs}
    encoded = {r: _encode_ref(r[0]) for r in set(lang_ref.values())}
    lang_rid = {lang: _ref_id(*r) for lang, r in lang_ref.items()}
    rid_for = lang_rid.get
    result, lock = {}, threading.Lock()
    tasks = []
    for lang, texts in jobs.items():
        need = list(dict.fromkeys(t for t in texts if t.strip() and not _store_file(store, lang, rid_for(lang), t).is_file()))
        result[lang] = [len(set(texts)) - len(need), 0]
        tasks += [(lang, need[i:i + BATCH]) for i in range(0, len(need), BATCH)]
    left = {lang: sum(1 for l, _ in tasks if l == lang) for lang in jobs}
    if not tasks:
        return {k: tuple(v) for k, v in result.items()}
    log(f'  Tạo sẵn giọng: {sum(len(c) for _, c in tasks)} câu, {len(tasks)} lượt, {parallel} lượt chạy cùng lúc trên GPU Modal')

    def run(lang, chunk):
        r = lang_ref[lang]
        data = _post(url, key, {'refs': {'r1': {'audio': encoded[r], 'text': r[1]}},
                                'items': [{'text': t, 'ref': 'r1', 'language': lang} for t in chunk]})
        got = 0
        for t, audio in zip(chunk, data.get('audios', [])):
            raw = base64.b64decode(audio)
            if _valid_audio(raw):  # rỗng thì không lưu: lúc render sẽ tự đọc lại câu đó
                _store_file(store, lang, rid_for(lang), t).write_bytes(raw)
                got += 1
        return lang, got, len(chunk)

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futs = {pool.submit(run, lang, chunk): lang for lang, chunk in tasks}
        for fut in as_completed(futs):
            lang = futs[fut]
            with lock:
                try:
                    _, got, want = fut.result()
                    result[lang][0] += got
                    result[lang][1] += want - got
                except Exception as e:  # noqa: BLE001 - lượt lỗi: khi render sẽ tự gọi lại Modal cho câu thiếu
                    result[lang][1] += 1
                    log(f'  [{lang}] tạo sẵn giọng: 1 lượt lỗi ({e}) — lúc render sẽ tự đọc bù')
                left[lang] -= 1
                if left[lang] == 0:
                    log(f'  [{lang}] tạo sẵn giọng xong: {result[lang][0]}/{len(set(jobs[lang]))} câu')
    return {k: tuple(v) for k, v in result.items()}
