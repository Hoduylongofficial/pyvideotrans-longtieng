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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from videotrans.configure.config import logger, params, ROOT_DIR
from videotrans.tts._dub_text import heard_too_long, scorable, similarity, speak_text

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
    # Chữ thực sự đọc (phat_am.json, số -> chữ); phụ đề vẫn giữ nguyên. Kho tạo sẵn khoá theo bản này
    spoken = {id(it): speak_text(it['text'], language) for it in todo}
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
                f = _store_file(store, language, rid, spoken[id(it)])
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
            item = {'text': spoken[id(it)], 'language': language}
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
                    _store_file(store, language, rid, spoken[id(it)]).write_bytes(raw)
                ok += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f'OmniVoice Modal: câu lỗi {it.get("line")}: {e}')
                err += 1
        logger.debug(f'OmniVoice Modal: {len(chunk)} câu, GPU {data.get("seconds")}s')
    return ok, err


def _spoken_seconds(raw: bytes) -> float:
    """配音在 pyvideotrans 里实际占用的时长：remove_silence_wav 按 -50 dBFS 去掉首尾静音，
    再补 80ms + 400ms 缓冲。这里按同样规则估算，用来判断是否超出字幕可用时长。"""
    import numpy as np
    import soundfile as sf
    wav, sr = sf.read(io.BytesIO(raw), dtype='float32', always_2d=True)
    x = wav.mean(axis=1)
    total = len(x) / sr
    hop = max(1, int(sr * 0.01))
    n = len(x) // hop
    if n == 0:
        return total
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9
    loud = np.where(20 * np.log10(rms) > -50)[0]
    if len(loud) == 0:
        return total
    return min(total, (loud[-1] - loud[0] + 1) * 0.01 + 0.48)


# Whisper nghe lại cả ngôn ngữ mà điểm trung vị dưới mức này = lỗi hệ thống, không phải câu hỏng lẻ:
# giọng mẫu tiếng Anh làm đọc lơ lớ (đo 10/2026: th 0.63, hi 0.77) hoặc Whisper yếu ngôn ngữ đó. Đọc lại
# không sửa được -> không đọc lại (đỡ tốn GPU), chỉ báo. Ngôn ngữ ổn có trung vị 0.92-1.00.
QC_HEALTHY_MEDIAN = 0.85
QC_MIN_SAMPLE = 8


def _median(values):
    v = sorted(values)
    return v[len(v) // 2] if len(v) >= QC_MIN_SAMPLE else None


def _qc_file(f: Path) -> Path:
    return f.with_suffix('.qc.json')


def _read_qc(f: Path):
    """(lời Whisper nghe lại, điểm) đã lưu cạnh file giọng; chưa kiểm thì None"""
    import json
    try:
        d = json.loads(_qc_file(f).read_text(encoding='utf-8'))
        return d.get('heard', ''), float(d['score'])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save(f: Path, raw: bytes, qc=None) -> None:
    import json
    f.write_bytes(raw)
    if qc:
        _qc_file(f).write_text(json.dumps({'heard': qc[0], 'score': round(qc[1], 3)}, ensure_ascii=False),
                               encoding='utf-8')
    else:
        _qc_file(f).unlink(missing_ok=True)


def prefetch(store: Path, jobs: dict, parallel: int = 4, log=print, native: set = frozenset(),
             slots: dict = None, fit_ratio: float = 0, on_ready=None,
             qc_min: float = 0, qc_retries: int = 2, on_qc=None, feed=None, order: list = None) -> dict:
    """固定参考音色下，把 {语言: [文本,...]} 全部预先合成进仓库；native 中的语言用本地口音音色。

    parallel 个请求同时在 Modal 上跑（每个请求一个 GPU 容器）。任务按语言顺序优先：前面的语言先合成完，
    on_ready(lang) 立即通知 dub_all 开始渲染该语言，不必等所有语言合成完（渲染在本机，比 GPU 慢得多）。

    Mỗi ngôn ngữ đi qua: synth -> redo (tối đa qc_retries vòng) -> fit -> ready.
    - qc_min > 0: server cho Whisper nghe lại từng câu vừa đọc; câu nào giống câu yêu cầu dưới qc_min
      (đọc sót, lặp, sai thứ tiếng, ra tiếng ậm ừ) thì đọc lại, giữ bản điểm cao nhất. Câu vẫn lệch sau
      các vòng đọc lại được báo qua on_qc(lang, [(câu, nghe được, điểm)], trung vị) để người dùng nghe kiểm.
      Cả ngôn ngữ nghe ra lệch (trung vị < QC_HEALTHY_MEDIAN) thì không đọc lại, trung vị báo kèm.
    - slots={语言: {文本: 可用秒数}} 且 fit_ratio>0 时：某句配音比可用时长长出 fit_ratio 倍以上，
      用 OmniVoice 的 duration 参数按可用时长重读该句（模型自然地说快一些），比事后用 rubberband
      硬加速自然得多；只重读超长的句子，不重读整批。
    Câu phụ đề được đổi sang chữ thực sự đọc (speak_text) trước khi tra kho / gửi đi, giống hệt
    synthesize_remote. 返回 {语言: (完成, 失败, 重读, 听写后重读改善)}。

    feed (queue.Queue): ngôn ngữ đến dần — dub_all đưa (mã, [câu], {câu: giây}) vào ngay khi dịch xong
    ngôn ngữ đó, None = hết. Có feed thì GPU tạo giọng song song với bước dịch thay vì chờ dịch đủ cả
    loạt. order = thứ tự ưu tiên (thứ tự render) của mọi ngôn ngữ, kể cả ngôn ngữ chưa tới.
    """
    import queue
    fixed = fixed_ref()
    if not fixed:
        return {}
    url, key = str(params['omnivoice_modal_url']).strip(), str(params['omnivoice_modal_key']).strip()
    store.mkdir(parents=True, exist_ok=True)
    initial, initial_slots = list(jobs.items()), slots or {}
    jobs, slots = {}, {}            # 语言 -> 实际朗读的句子 / {句子: 可用秒数}，add() 逐个语言填入
    lang_ref, rid, encoded = {}, {}, {}
    # 优先级按 dub_all 的语言顺序（渲染顺序），后加入的语言也照此排队
    order = {lang: i for i, lang in enumerate(order or [lang for lang, _ in initial])}
    result = {}
    lock = threading.Lock()
    tasks = queue.PriorityQueue()   # (优先级, 序号, 类型, 语言, 句子)：重读 > 按语言顺序的合成
    seq = iter(range(10 ** 9))
    left = {}                       # 语言 -> 未完成的任务数
    phase, rounds = {}, {}
    scored = {}                     # câu đọc trong lần chạy này -> điểm (chỉ những câu này mới đọc lại)
    done_langs = set()
    fed_all = threading.Event()     # feed đã đưa hết ngôn ngữ (không có feed: ngay từ đầu)

    def file_of(lang, text):
        return _store_file(store, lang, rid[lang], text)

    def post(lang, items):
        r = lang_ref[lang]
        body = {'refs': {'r1': {'audio': encoded[r], 'text': r[1]}},
                'items': [dict(it, ref='r1', language=lang) for it in items]}
        if qc_min > 0:
            body['asr'] = True
        return _post(url, key, body)

    def outputs(lang, texts, data):
        """[(câu, raw, (nghe được, điểm) hoặc None)] theo đúng thứ tự texts; câu rỗng -> raw None"""
        heard = data.get('heard') or []
        out = []
        for n, (t, audio) in enumerate(zip(texts, data.get('audios', []))):
            raw = base64.b64decode(audio)
            if not _valid_audio(raw):   # rỗng thì không lưu: lúc render sẽ tự đọc lại câu đó
                out.append((t, None, None))
                continue
            # Chấm trên toàn bộ lời nghe được (lặp vòng thì điểm thấp), chỉ lưu đoạn đầu cho báo cáo.
            # Câu quá ngắn / Whisper tự bịa câu: không chấm (scorable)
            qc = (heard[n][:300], similarity(t, heard[n], lang))                 if n < len(heard) and scorable(t, heard[n], lang) else None
            out.append((t, raw, qc))
        # Whisper hay tự lặp vòng / bịa câu ("Υπότιτλοι AUTHORWAVE...") trên âm thanh bình thường. Nghe ra
        # dài gấp đôi câu mà âm thanh không dài bất thường (tốc độ đọc >= 0.6 trung vị cả lượt) = Whisper
        # hỏng, không phải TTS lặp -> không chấm câu đó (không đọc lại, không báo). Đo 10/2026 (el):
        # câu Whisper ra 300 ký tự lặp có âm thanh 2.8s / khung 3.0s.
        rates = {t: len(t) / max(_spoken_seconds(raw) - 0.48, 0.1) for t, raw, _ in out if raw}
        med = sorted(rates.values())[len(rates) // 2] if len(rates) >= 4 else None
        for i, (t, raw, qc) in enumerate(out):
            if qc and med and rates[t] >= 0.6 * med and heard_too_long(t, qc[0], lang):
                out[i] = (t, raw, None)
        return out

    def ready(lang):
        if lang in done_langs:
            return
        done_langs.add(lang)
        ok, err, refit, fixed_n = result[lang]
        extra = f', {refit} câu đọc lại cho vừa khung' if refit else ''
        if fixed_n:
            extra += f', {fixed_n} câu đọc lại vì nghe sai'
        bad, med = [], None
        if qc_min > 0:
            checked = [(t, _read_qc(file_of(lang, t))) for t in dict.fromkeys(jobs[lang])]
            checked = [(t, qc) for t, qc in checked if qc]
            bad = [(t, qc[0], qc[1]) for t, qc in checked if qc[1] < qc_min]
            med = _median([qc[1] for _, qc in checked])
            if med is not None and med < QC_HEALTHY_MEDIAN:
                extra += f', Whisper nghe cả ngôn ngữ lệch (trung vị {med:.2f}) — có thể giọng lơ lớ'
            elif bad:
                extra += f', {len(bad)} câu nghe lại vẫn lệch'
        log(f'  [{lang}] tạo sẵn giọng xong: {ok}/{len(set(jobs[lang]))} câu{extra}')
        if on_qc and qc_min > 0:
            on_qc(lang, bad, med)
        if on_ready:
            on_ready(lang)

    def plan_redo(lang) -> list:
        """Câu đọc trong lần chạy này mà Whisper nghe ra lệch"""
        if qc_min <= 0 or rounds[lang] >= qc_retries:
            return []
        med = _median(scored[lang].values())
        if med is not None and med < QC_HEALTHY_MEDIAN:
            return []
        return [t for t, score in scored[lang].items() if score < qc_min]

    def plan_fit(lang) -> list:
        """该语言合成完后找出超长的句子：[(文本, 请求时长, 原占用时长)]"""
        if fit_ratio <= 0 or not slots.get(lang):
            return []
        out = []
        for text, window in slots[lang].items():
            f = file_of(lang, text)
            if not f.is_file() or window <= 0:
                continue
            spoken = _spoken_seconds(f.read_bytes())
            if spoken > window * fit_ratio:
                speech = spoken - 0.48
                # 目标：去静音+缓冲后正好放进可用时长；最多让模型说快 1.6 倍，剩下的交给 rubberband
                out.append((text, round(max(window - 0.4, speech / 1.6, 0.5), 2), spoken))
        return out

    def enqueue(lang, kind, items, priority):
        chunks = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
        left[lang] = len(chunks)
        phase[lang] = kind
        for c in chunks:
            tasks.put((priority, next(seq), kind, lang, c))

    def finish_task(lang):
        left[lang] -= 1
        if left[lang] > 0:
            return
        if phase[lang] in ('synth', 'redo'):
            redo = plan_redo(lang)
            if redo:
                rounds[lang] += 1
                enqueue(lang, 'redo', redo, 0)
                return
            fits = plan_fit(lang)
            if fits:
                enqueue(lang, 'fit', fits, 0)
                return
        ready(lang)

    def add(lang, texts, win, start=True):
        """Đưa 1 ngôn ngữ vào hàng đợi GPU. start=False: chưa cho render ngay dù đã đủ trong kho."""
        # Chữ thực sự đọc; khung thời gian theo câu phụ đề tương ứng (trùng thì lấy khung ngắn nhất)
        spoken = [speak_text(t, lang) for t in texts]
        w = {}
        for t, window in (win or {}).items():
            k = speak_text(t, lang)
            w[k] = min(window, w.get(k, window))
        # 每种语言一个参考音色：默认固定参考音色，native 语言用本地口音参考音频（可能要上 Modal 生成，锁外做）
        r = native_ref(lang, spoken, url, key) if lang in native else fixed
        enc = None if r in encoded else _encode_ref(r[0])
        with lock:
            if enc is not None:
                encoded[r] = enc
            jobs[lang], slots[lang], lang_ref[lang], rid[lang] = spoken, w, r, _ref_id(*r)
            order.setdefault(lang, len(order))
            result[lang], phase[lang], rounds[lang], scored[lang] = [0, 0, 0, 0], 'synth', 0, {}
            need = list(dict.fromkeys(t for t in spoken if t.strip() and not file_of(lang, t).is_file()))
            result[lang][0] = len(set(spoken)) - len(need)
            enqueue(lang, 'synth', need, 1 + order[lang])
            if start and left[lang] == 0:  # 已全部在仓库中：检查一下超长句后即可渲染
                left[lang] = 1
                finish_task(lang)

    for lang, texts in initial:
        add(lang, texts, initial_slots.get(lang), start=False)
    total = sum(left.values())
    if total or feed is not None:
        log(f'  Tạo sẵn giọng: {parallel} lượt chạy cùng lúc trên GPU Modal (ngôn ngữ nào xong là render ngay'
            + ('; ngôn ngữ nào dịch xong là đưa lên GPU ngay' if feed is not None else f', {total} lượt') + ')'
            + (', Whisper nghe lại từng câu' if qc_min > 0 else ''))
    for lang in list(jobs):  # 已全部在仓库中的语言：检查一下超长句后即可渲染
        if left[lang] == 0:
            left[lang] = 1
            finish_task(lang)

    def feeder():
        """dub_all đưa (ngôn ngữ, câu, khung thời gian) vào feed ngay khi dịch xong; None = hết."""
        while True:
            item = feed.get()
            if item is None:
                break
            lang = item[0]
            try:
                add(*item)
            except Exception as e:  # noqa: BLE001 - lúc render sẽ tự gọi Modal cho câu thiếu
                log(f'  [{lang}] tạo sẵn giọng lỗi ({e}) — lúc render sẽ tự đọc')
                if on_ready:
                    on_ready(lang)
        fed_all.set()

    if feed is None:
        fed_all.set()
    else:
        threading.Thread(target=feeder, daemon=True).start()

    def worker():
        while True:
            try:
                _, _, kind, lang, chunk = tasks.get(timeout=0.5)
            except queue.Empty:
                with lock:
                    if fed_all.is_set() and all(v <= 0 for v in left.values()):
                        return
                continue
            try:
                if kind == 'synth':
                    got = [x for x in outputs(lang, chunk, post(lang, [{'text': t} for t in chunk])) if x[1]]
                    for t, raw, qc in got:
                        _save(file_of(lang, t), raw, qc)
                    with lock:
                        result[lang][0] += len(got)
                        result[lang][1] += len(chunk) - len(got)
                        scored[lang].update({t: qc[1] for t, _, qc in got if qc})
                elif kind == 'redo':
                    better = 0
                    for t, raw, qc in outputs(lang, chunk, post(lang, [{'text': t} for t in chunk])):
                        # Model có ngẫu nhiên nên đọc lại thường ra bản khác; chỉ thay khi nghe khớp hơn
                        if raw and qc and qc[1] > scored[lang].get(t, 0):
                            _save(file_of(lang, t), raw, qc)
                            with lock:
                                if scored[lang].get(t, 0) < qc_min <= qc[1]:
                                    better += 1
                                scored[lang][t] = qc[1]
                    with lock:
                        result[lang][3] += better
                else:
                    data = post(lang, [{'text': t, 'duration': d} for t, d, _ in chunk])
                    better = 0
                    for (t, _, old), (_, raw, qc) in zip(chunk, outputs(lang, [c[0] for c in chunk], data)):
                        # 只有确实变短了才替换，模型偶尔会读坏或不按时长；đọc nhanh mà nghe ra lệch hơn thì bỏ
                        prev = _read_qc(file_of(lang, t))
                        ok_qc = not qc or not prev or qc[1] >= min(qc_min, prev[1])
                        if raw and _spoken_seconds(raw) < old and ok_qc:
                            _save(file_of(lang, t), raw, qc)
                            better += 1
                    with lock:
                        result[lang][2] += better
            except Exception as e:  # noqa: BLE001 - lượt lỗi: khi render sẽ tự gọi lại Modal cho câu thiếu
                with lock:
                    if kind == 'synth':
                        result[lang][1] += len(chunk)
                log(f'  [{lang}] tạo sẵn giọng: 1 lượt lỗi ({e}) — lúc render sẽ tự đọc bù')
            finally:
                with lock:
                    finish_task(lang)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, parallel))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for lang in jobs:  # 出错也要放行，渲染时会自己补读缺的句子
        ready(lang)
    return {k: tuple(v) for k, v in result.items()}
