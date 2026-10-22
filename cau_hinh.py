# -*- coding: utf-8 -*-
"""
Lõi của CAI_DAT.bat (trang cài đặt cai_dat.py): đọc / ghi cài đặt, không có giao diện.

Cài đặt nằm ở 3 chỗ trên mỗi máy, cộng 1 file chung cho mọi máy:
  - videotrans/params.json   : key, model, URL máy chủ...          (không lên GitHub)
  - videotrans/cfg.json      : cài đặt nâng cao (llm_timeout...)     (không lên GitHub)
  - dub_all.config.json      : cấu hình lồng tiếng (có trên GitHub). CAP_NHAT.bat chỉ giữ lại vài mục của máy
                               (cap_nhat.KEEP_DUB_VALUES) nên mục khác ghi vào dub_all.local.json (không lên GitHub)
  - cau_hinh_chung.json      : cấu hình chung (có trên GitHub), thắng giá trị riêng của máy. Chỉ máy quản trị
                               (có thư mục .git) sửa + đẩy lên. Không bao giờ chứa key / URL máy chủ riêng.
"""
import importlib.util
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cap_nhat import KEEP_DUB_VALUES
import doi_model

ROOT_DIR = Path(__file__).resolve().parent
PARAMS_JSON = ROOT_DIR / 'videotrans' / 'params.json'
CFG_JSON = ROOT_DIR / 'videotrans' / 'cfg.json'
DUB_CONFIG = ROOT_DIR / 'dub_all.config.json'
LOCAL_CONFIG = ROOT_DIR / 'dub_all.local.json'

# videotrans/configure/_shared_cfg.py nạp thẳng file: import videotrans sẽ khởi tạo cả phần mềm
_spec = importlib.util.spec_from_file_location('_shared_cfg', ROOT_DIR / 'videotrans' / 'configure' / '_shared_cfg.py')
shared_cfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared_cfg)
SHARED_JSON = shared_cfg.shared_path(ROOT_DIR)
# Tên kho lưu trong trang cài đặt -> tên phần trong cau_hinh_chung.json
SECTION = {'params': 'params', 'settings': 'settings', 'dub': 'dub_all'}


@dataclass(frozen=True)
class Field:
    store: str            # params | settings | dub
    key: str
    label: str
    kind: str = 'text'    # text | int | float | bool | choice | auto_int | secret | lines
    default: object = None
    choices: tuple = ()   # ((giá trị, nhãn), ...) cho kind="choice"
    help: str = ''
    minimum: float = None
    maximum: float = None

    @property
    def id(self) -> str:
        return f'{self.store}.{self.key}'

    @property
    def shareable(self) -> bool:
        return self.kind != 'secret' and not shared_cfg.is_private(self.key)


CHANNEL_CHOICES = ((25, '9Router (VPS riêng)'), (10, 'OpenRouter'), (6, 'Gemini (Google AI Studio)'),
                   (5, 'DeepSeek chính hãng'), (0, 'Google Dịch (miễn phí, chất lượng thấp)'))
TTS_CHOICES = ((0, 'Edge-TTS (online, miễn phí)'), (3, 'OmniVoice trên GPU thuê Modal (nhái giọng)'))

FIELDS = [
    # --- Dịch
    Field('dub', 'translate_type', 'Kênh dịch', 'choice', 25, CHANNEL_CHOICES),
    Field('params', 'ninerouter_api', 'URL 9Router (dạng https://<tên miền>/v1)', 'text', ''),
    Field('params', 'ninerouter_model', 'Chuỗi model 9Router (mỗi dòng 1 model, dòng trên ưu tiên trước)', 'lines', '',
          help='Model đầu lỗi (hết lượt, 404, 503, treo quá thời gian chờ) thì tự chuyển sang model dòng dưới.'),
    Field('params', 'openrouter_model', 'Model OpenRouter', 'lines', ''),
    Field('params', 'gemini_model', 'Model Gemini', 'lines', ''),
    Field('params', 'deepseek_model', 'Model DeepSeek chính hãng', 'lines', ''),
    Field('dub', 'translate_parallel', 'Số ngôn ngữ dịch cùng lúc', 'int', 4, minimum=1, maximum=8),
    Field('settings', 'llm_timeout', 'Chờ AI trả lời tối đa (giây) rồi chuyển model dự phòng', 'int', 300,
          minimum=60, maximum=1800),
    Field('dub', 'translate_stall_minutes', 'Dịch 1 ngôn ngữ bao nhiêu phút không phản hồi thì coi là treo',
          'int', 20, minimum=0, maximum=240),
    Field('dub', 'translate_qa', 'Soát bản dịch trước khi lồng tiếng', 'bool', True),
    Field('dub', 'translate_glossary', 'Bảng thuật ngữ khi dịch', 'bool', True),
    Field('dub', 'merge_fragments', 'Gộp câu phụ đề bị cắt đôi trước khi dịch', 'bool', True),
    Field('dub', 'tts_speak_text', 'AI viết lại số / ký hiệu thành chữ để đọc', 'bool', True),
    # --- Giọng đọc
    Field('dub', 'tts_type', 'Giọng đọc', 'choice', 0, TTS_CHOICES),
    Field('params', 'omnivoice_modal_url', 'URL server OmniVoice (Modal)', 'text', ''),
    Field('params', 'omnivoice_modal_key', 'Key server OmniVoice (Modal)', 'secret', ''),
    Field('params', 'runpod_endpoint_id', 'Endpoint ID RunPod (GPU dự phòng khi Modal hết hạn mức)', 'text', ''),
    Field('params', 'runpod_api_key', 'API key RunPod', 'secret', ''),
    # --- Telegram
    Field('params', 'telegram_bot_token', 'Token bot Telegram', 'secret', ''),
    Field('params', 'telegram_chat_id', 'ID nhóm Telegram', 'text', ''),
    Field('dub', 'telegram_notify', 'Khi nào gửi báo cáo', 'choice', 'always',
          (('always', 'Lượt nào cũng gửi'), ('errors', 'Chỉ khi có lỗi / cảnh báo'), ('off', 'Tắt'))),
    # --- Lồng tiếng & render
    Field('dub', 'is_separate', 'Tách nhạc nền + SFX, giữ lại dưới giọng đọc mới', 'bool', True),
    Field('dub', 'backaudio_volume', 'Độ to nhạc nền', 'float', 0.5, minimum=0, maximum=3),
    Field('dub', 'dub_parallel', 'Số video render cùng lúc ("auto" hoặc số)', 'auto_int', 'auto', minimum=1, maximum=8),
    Field('dub', 'dub_prep_ahead', 'Số ngôn ngữ chuẩn bị tiếng trước ("auto" hoặc số)', 'auto_int', 'auto',
          minimum=0, maximum=8),
    Field('dub', 'tts_prefetch_parallel', 'Số lượt tạo giọng cùng lúc trên GPU ("auto" hoặc số)', 'auto_int', 'auto',
          minimum=1, maximum=8),
    Field('dub', 'tts_fit_ratio', 'Đọc lại trên GPU câu dài hơn khung quá (lần)', 'float', 1.3, minimum=0, maximum=3),
    Field('dub', 'tts_shorten_ratio', 'Viết ngắn câu đọc quá nhanh từ (lần)', 'float', 1.3, minimum=0, maximum=3),
    Field('dub', 'dub_stall_minutes', 'Lồng tiếng 1 ngôn ngữ bao nhiêu phút không phản hồi thì coi là treo',
          'int', 30, minimum=0, maximum=600),
    Field('dub', 'retries', 'Số lần thử lại 1 ngôn ngữ bị lỗi', 'int', 2, minimum=0, maximum=5),
    Field('dub', 'video_preset', 'Tốc độ mã hoá video', 'choice', 'veryfast',
          tuple((p, p) for p in ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium'))),
    Field('dub', 'video_crf', 'Chất lượng video (CRF, nhỏ hơn = nét hơn, file to hơn)', 'int', 21,
          minimum=14, maximum=32),
    Field('dub', 'normalize_audio', 'Cân bằng âm lượng về chuẩn YouTube', 'bool', True),
    Field('dub', 'loudnorm_i', 'Âm lượng chuẩn (LUFS)', 'float', -14, minimum=-30, maximum=-8),
    Field('dub', 'cleanup_out', 'Xoá file trung gian sau khi render xong', 'bool', True),
]
BY_ID = {f.id: f for f in FIELDS}


# ---------------------------------------------------------------------------
# Đọc
# ---------------------------------------------------------------------------
def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict, indent=None) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + ('\n' if indent else ''), encoding='utf-8')
    os.replace(tmp, path)


def is_admin() -> bool:
    """Máy quản trị = bản clone git (máy nhân viên cài từ zip, không có .git)"""
    return (ROOT_DIR / '.git').is_dir()


def local_values(store: str) -> dict:
    if store == 'params':
        return read_json(PARAMS_JSON)
    if store == 'settings':
        return read_json(CFG_JSON)
    values = read_json(DUB_CONFIG)
    values.update({k: v for k, v in read_json(LOCAL_CONFIG).items() if not k.startswith('_')})
    return values


def shared_values() -> dict:
    """{store: {mục: giá trị}} trong cau_hinh_chung.json"""
    data = shared_cfg.read_all(ROOT_DIR)
    return {store: data.get(section, {}) for store, section in SECTION.items()}


def snapshot() -> dict:
    """Giá trị đang có hiệu lực + nguồn: {id: (giá trị, 'chung' | 'máy')}"""
    local = {s: local_values(s) for s in SECTION}
    shared = shared_values()
    out = {}
    for f in FIELDS:
        if f.key in shared[f.store]:
            out[f.id] = (shared[f.store][f.key], 'chung')
        else:
            out[f.id] = (local[f.store].get(f.key, f.default), 'máy')
    return out


def note(field: Field) -> str:
    """Giải thích của mục: help trong FIELDS, không có thì lấy "_<mục>_note" trong dub_all.config.json"""
    # Ô chọn đã có nhãn tiếng Việt: ghi chú trong file chỉ là bảng mã số
    if field.help or field.store != 'dub' or field.kind == 'choice':
        return field.help
    return str(read_json(DUB_CONFIG).get(f'_{field.key}_note', '') or '')


def mask(value) -> str:
    value = str(value or '')
    return doi_model.mask(value) if value else 'chưa có'


def to_display(field: Field, value):
    if field.kind == 'lines':
        return '\n'.join(m.strip() for m in str(value or '').split(',') if m.strip())
    if field.kind == 'choice':
        return value
    if field.kind == 'secret':
        return ''
    return value


# ---------------------------------------------------------------------------
# Kiểm tra + đổi kiểu giá trị nhập trên trang
# ---------------------------------------------------------------------------
def convert(field: Field, raw):
    """Giá trị từ ô nhập -> giá trị lưu. Sai thì ValueError (thông báo tiếng Việt)."""
    if field.kind == 'bool':
        return bool(raw)
    if field.kind == 'lines':
        models = [m.strip() for m in re.split(r'[\n,;]+', str(raw or '')) if m.strip()]
        return ','.join(dict.fromkeys(models))
    if field.kind == 'choice':
        values = [v for v, _ in field.choices]
        for v in values:
            if str(v) == str(raw):
                return v
        raise ValueError(f'{field.label}: "{raw}" không có trong danh sách')
    if field.kind == 'auto_int':
        text = str(raw if raw is not None else '').strip().lower()
        if text in ('', 'auto'):
            return 'auto'
        return _number(field, text, int)
    if field.kind == 'int':
        return _number(field, raw, int)
    if field.kind == 'float':
        return _number(field, raw, float)
    text = str(raw or '').strip().strip('"')
    if field.key == 'ninerouter_api' and text:
        text = doi_model.ninerouter_url(text)
    return text


def _number(field: Field, raw, cast):
    try:
        value = float(str(raw).strip().replace(',', '.'))
    except ValueError:
        raise ValueError(f'{field.label}: "{raw}" không phải số') from None
    if cast is int:
        if value != int(value):
            raise ValueError(f'{field.label}: phải là số nguyên')
        value = int(value)
    if field.minimum is not None and value < field.minimum or field.maximum is not None and value > field.maximum:
        raise ValueError(f'{field.label}: phải trong khoảng {field.minimum:g} - {field.maximum:g}')
    return value


# ---------------------------------------------------------------------------
# Ghi
# ---------------------------------------------------------------------------
def save(values: dict, admin: bool = None) -> list:
    """values = {id: giá trị nhập}. Ô bí mật để trống = giữ nguyên. Trả về danh sách thông báo.
    Mục nằm trong cấu hình chung: máy quản trị ghi vào cấu hình chung, máy khác bỏ qua."""
    admin = is_admin() if admin is None else admin
    shared = shared_values()
    current = snapshot()
    changes = {'params': {}, 'settings': {}, 'dub': {}}
    shared_changes = {}
    msgs, errors = [], []
    for fid, raw in values.items():
        field = BY_ID[fid]
        if field.kind == 'secret' and not str(raw or '').strip():
            continue
        try:
            value = convert(field, raw)
        except ValueError as e:
            errors.append(str(e))
            continue
        if value == current[fid][0]:
            continue
        if field.key in shared[field.store]:
            if not admin:
                msgs.append(f'Bỏ qua "{field.label}": mục này do quản trị đặt chung cho mọi máy.')
                continue
            shared_changes[fid] = value
        changes[field.store][field.key] = value
        msgs.append(f'Đã đổi "{field.label}"' + (' (cấu hình chung)' if fid in shared_changes else ''))
    if errors:
        return [f'LỖI: {e}' for e in errors] + ['Chưa lưu gì, sửa lại rồi bấm Lưu.']
    _write_local(changes)
    if shared_changes:
        set_shared({fid: v for fid, v in shared_changes.items()})
    return msgs or ['Không có gì thay đổi.']


def _write_local(changes: dict) -> None:
    for store, path in (('params', PARAMS_JSON), ('settings', CFG_JSON)):
        if changes[store]:
            data = read_json(path)
            data.update(changes[store])
            write_json(path, data)
    if changes['dub']:
        local = read_json(LOCAL_CONFIG)
        for key, value in changes['dub'].items():
            # Mục CAP_NHAT giữ lại thì ghi thẳng vào dub_all.config.json như DOI_MODEL.bat vẫn làm
            if key in KEEP_DUB_VALUES and set_dub_line(key, value):
                local.pop(key, None)
            else:
                local[key] = value
        local.setdefault('_note', 'Chinh rieng cua may nay (CAI_DAT.bat ghi), de len dub_all.config.json. '
                                  'Khong len GitHub, CAP_NHAT.bat khong dung toi.')
        write_json(LOCAL_CONFIG, local, indent=2)


def set_dub_line(name: str, value) -> bool:
    """Thay đúng giá trị của 1 mục cấp ngoài cùng, giữ nguyên định dạng + ghi chú của dub_all.config.json"""
    raw = DUB_CONFIG.read_text(encoding='utf-8')
    new, n = re.subn(rf'^(\s{{2}}"{re.escape(name)}"\s*:\s*)(-?\d+(?:\.\d+)?|true|false|null|"[^"\n]*")',
                     lambda m: m.group(1) + json.dumps(value, ensure_ascii=False), raw, count=1, flags=re.M)
    if not n:
        return False
    DUB_CONFIG.write_text(new, encoding='utf-8')
    return True


def set_shared(values: dict) -> None:
    """values = {id: giá trị | None (bỏ khỏi cấu hình chung)}"""
    data = read_json(SHARED_JSON) or {'_note': ''}
    for fid, value in values.items():
        field = BY_ID[fid]
        if not field.shareable:
            raise ValueError(f'"{field.label}" là thông tin riêng của máy, không đưa lên cấu hình chung')
        section = data.setdefault(SECTION[field.store], {})
        if value is None:
            section.pop(field.key, None)
        else:
            section[field.key] = value
    for section in SECTION.values():
        data.setdefault(section, {})
    write_json(SHARED_JSON, data, indent=2)


def choose_shared(ids: list) -> list:
    """Đặt danh sách mục dùng chung = ids. Mục mới lấy giá trị đang dùng trên máy này; mục bị bỏ thì máy này
    giữ giá trị đó làm giá trị riêng (không bị đổi ngược)."""
    current = snapshot()
    shared = shared_values()
    now = {f.id for f in FIELDS if f.key in shared[f.store]}
    wanted = set(ids)
    updates, msgs = {}, []
    for fid in wanted - now:
        updates[fid] = current[fid][0]
        msgs.append(f'Thêm vào cấu hình chung: {BY_ID[fid].label} = {current[fid][0]!r}')
    removed = now - wanted
    if removed:
        changes = {'params': {}, 'settings': {}, 'dub': {}}
        for fid in removed:
            changes[BY_ID[fid].store][BY_ID[fid].key] = current[fid][0]
            updates[fid] = None
            msgs.append(f'Bỏ khỏi cấu hình chung: {BY_ID[fid].label}')
        _write_local(changes)
    if updates:
        set_shared(updates)
    return msgs or ['Không có gì thay đổi.']


def push_shared() -> tuple:
    """Commit riêng cau_hinh_chung.json rồi đẩy lên GitHub. Trả về (thành công, nội dung báo)."""
    raw = read_json(SHARED_JSON)
    leaked = [k for s in SECTION.values() for k in (raw.get(s) or {}) if shared_cfg.is_private(k)]
    if leaked:
        return False, f'Không đẩy: cấu hình chung có mục riêng tư {leaked}. Bỏ các mục đó ra trước.'

    def git(*args):
        return subprocess.run(['git', *args], cwd=ROOT_DIR, capture_output=True, text=True,
                              encoding='utf-8', errors='replace')

    branch = git('rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
    if branch != 'main':
        return False, f'Không đẩy: máy này đang ở nhánh "{branch}", cần nhánh main.'
    if not git('status', '--porcelain', '--', shared_cfg.SHARED_NAME).stdout.strip():
        return True, 'Cấu hình chung không có gì mới để đẩy.'
    names = ', '.join(sorted(k for s in SECTION.values() for k in (raw.get(s) or {}))) or 'trống'
    r = git('commit', '-m', f'Cấu hình chung cho mọi máy: {names}', '--', shared_cfg.SHARED_NAME)
    if r.returncode:
        return False, 'Commit lỗi:\n' + (r.stdout + r.stderr).strip()
    r = git('push', 'origin', 'main')
    if r.returncode:
        return False, ('Đã commit nhưng đẩy lên GitHub lỗi (thử chạy "git pull --rebase" rồi bấm lại):\n'
                       + (r.stdout + r.stderr).strip())
    return True, 'Đã đẩy lên GitHub. Máy nhân viên chạy CAP_NHAT.bat là áp dụng.'


# ---------------------------------------------------------------------------
# API key + thử model
# ---------------------------------------------------------------------------
KEY_CHANNELS = {c: doi_model.CHANNELS[c] for c in doi_model.KEY_CHANNELS}


def set_params(**kv) -> None:
    """Ghi thẳng vài mục không có ô riêng trên trang (giọng mẫu OmniVoice...) vào params.json"""
    data = read_json(PARAMS_JSON)
    data.update(kv)
    write_json(PARAMS_JSON, data)


def get_keys(channel: int) -> list:
    return doi_model.get_keys(read_json(PARAMS_JSON), channel)


def set_keys(channel: int, keys: list) -> None:
    data = read_json(PARAMS_JSON)
    data[KEY_CHANNELS[channel]['key']] = ','.join(dict.fromkeys(k.strip() for k in keys if k.strip()))
    write_json(PARAMS_JSON, data)


def channel_model(channel: int) -> str:
    """Chuỗi model đang có hiệu lực của kênh (cấu hình chung thắng)"""
    fid = f'params.{doi_model.CHANNELS[channel]["model"]}'
    return str(snapshot()[fid][0] or '') if fid in BY_ID else ''


def ninerouter_models() -> list:
    import httpx
    params = read_json(PARAMS_JSON)
    url = doi_model.ninerouter_url(str(snapshot()['params.ninerouter_api'][0] or ''))
    keys = doi_model.get_keys(params, doi_model.NINEROUTER)
    if not url:
        raise ValueError('Chưa nhập URL 9Router')
    resp = httpx.get(f'{url}/models', timeout=30, headers={'Authorization': f'Bearer {keys[0]}'} if keys else None)
    resp.raise_for_status()
    return sorted({m['id'] for m in resp.json().get('data', []) if m.get('id')})


def check_ninerouter_key(key: str) -> tuple:
    """('OK' | 'LỖI', giây, ghi chú)"""
    import time
    import httpx
    url = doi_model.ninerouter_url(str(snapshot()['params.ninerouter_api'][0] or ''))
    started = time.time()
    try:
        r = httpx.get(f'{url}/models', timeout=30, headers={'Authorization': f'Bearer {key}'})
    except Exception as e:  # noqa: BLE001
        return 'LỖI', round(time.time() - started, 1), f'Không kết nối được: {e}'
    secs = round(time.time() - started, 1)
    if r.status_code == 200:
        return 'OK', secs, f'{len(r.json().get("data", []))} model'
    return 'LỖI', secs, f'{r.status_code} {doi_model.explain_error(r.status_code, r.text)} {r.text[:200]}'.strip()


def test_ninerouter(models: list, timeout: int = 90) -> list:
    """Thử song song từng model qua 9Router, mỗi model 1 lần (không tự thử lại như thư viện openai): model chết
    chỉ tốn tối đa timeout giây. [(model, 'OK' | 'LỖI', giây, câu trả về / giải thích lỗi)] theo thứ tự models."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    import httpx
    params = read_json(PARAMS_JSON)
    url = doi_model.ninerouter_url(str(snapshot()['params.ninerouter_api'][0] or ''))
    keys = doi_model.get_keys(params, doi_model.NINEROUTER)
    if not url or not keys:
        return [(m, 'LỖI', 0, 'Chưa có URL hoặc key 9Router') for m in models]
    prompt = f'Translate into French. Reply with the translation only.\n\n{doi_model.TEST_TEXT}'

    def one(model):
        started = time.time()
        try:
            r = httpx.post(f'{url}/chat/completions', timeout=timeout, headers={'Authorization': f'Bearer {keys[0]}'},
                           json={'model': model, 'stream': False, 'max_tokens': 4096,
                                 'messages': [{'role': 'user', 'content': prompt}]})
            secs = round(time.time() - started, 1)
            body = r.json() if r.content else {}
            if r.status_code == 200 and body.get('choices'):
                text = (body['choices'][0].get('message') or {}).get('content') or ''
                return (model, 'OK', secs, text.strip()) if text.strip() else (model, 'LỖI', secs, 'trả về rỗng')
            err = body.get('error') if isinstance(body, dict) else None
            msg = (err.get('message') if isinstance(err, dict) else err) or r.text[:300]
            hint = doi_model.explain_error(r.status_code, msg)
            return model, 'LỖI', secs, f'{r.status_code} {hint} {msg}'.strip()
        except httpx.TimeoutException:
            return model, 'LỖI', round(time.time() - started, 1), f'Treo, quá {timeout} giây không trả lời'
        except Exception as e:  # noqa: BLE001
            return model, 'LỖI', round(time.time() - started, 1), f'{type(e).__name__}: {e}'

    with ThreadPoolExecutor(max_workers=min(8, len(models)) or 1) as pool:
        return list(pool.map(one, models))


def test_models(channel: int, models: list, key: str = None) -> list:
    """Dịch thử 1 câu với từng model. [(model, 'OK' | 'LỖI', giây, câu trả về / giải thích lỗi)]"""
    params = read_json(PARAMS_JSON)
    params['ninerouter_api'] = snapshot()['params.ninerouter_api'][0]
    keys = [key] if key else doi_model.get_keys(params, channel)
    if not keys:
        return [(m, 'LỖI', 0, 'Chưa có API key cho kênh này') for m in models]
    rows = []
    for model in models:
        ok, text, secs, code = doi_model.test_one(channel, model, keys[0], params)
        hint = '' if ok else doi_model.explain_error(code, text)
        rows.append((model, 'OK' if ok else 'LỖI', round(secs, 1), text if ok else f'{hint} {text}'.strip()))
    return rows
