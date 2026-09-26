# -*- coding: utf-8 -*-
"""
Đổi kênh dịch / model / API key cho LONG_TIENG.bat và phần mềm (DOI_MODEL.bat).

Ghi vào:
  - dub_all.config.json  : "translate_type", "translate_parallel" (chỉ sửa đúng dòng đó)
  - videotrans/params.json: <kênh>_model, <kênh>_key (nhiều key cách nhau dấu phẩy)
  - videotrans/cfg.json   : thêm model vào danh sách để giao diện hiển thị được

Nhiều key: phần mềm dùng xoay vòng, key nào bị giới hạn (429) / hết tiền / sai thì
tự chuyển sang key tiếp theo.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def _force_utf8_console() -> None:
    """Console Windows mặc định không phải UTF-8 nên chữ tiếng Việt sẽ làm crash print()."""
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001 - chỉ là cải thiện hiển thị
            pass
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


_force_utf8_console()

ROOT_DIR = Path(__file__).resolve().parent
PARAMS_JSON = ROOT_DIR / 'videotrans' / 'params.json'
CFG_JSON = ROOT_DIR / 'videotrans' / 'cfg.json'
DUB_CONFIG = ROOT_DIR / 'dub_all.config.json'
CLI_PY = ROOT_DIR / 'cli.py'

PAID_OPENROUTER_MODEL = 'deepseek/deepseek-v4.1-flash'
PAID_PARALLEL = 4
FREE_PARALLEL = 1

OPENROUTER, GEMINI, DEEPSEEK, GOOGLE, NINEROUTER = 10, 6, 5, 0, 25
CHANNELS = {
    OPENROUTER: {'name': 'OpenRouter', 'key': 'openrouter_key', 'model': 'openrouter_model',
                 'prefix': ('sk-or-',)},
    GEMINI: {'name': 'Gemini (Google AI Studio)', 'key': 'gemini_key', 'model': 'gemini_model',
             'prefix': ('AIza', 'AQ.')},
    DEEPSEEK: {'name': 'DeepSeek chính hãng', 'key': 'deepseek_key', 'model': 'deepseek_model',
               'prefix': ('sk-',)},
    GOOGLE: {'name': 'Google Dịch (miễn phí)', 'key': None, 'model': None, 'prefix': ()},
    NINEROUTER: {'name': '9Router (VPS riêng)', 'key': 'ninerouter_key', 'model': 'ninerouter_model',
                 'prefix': ('sk-',)},
}
KEY_CHANNELS = [OPENROUTER, GEMINI, DEEPSEEK, NINEROUTER]
GEMINI_EXTRA_MODELS = ['gemini-2.5-flash', 'gemini-2.5-flash-lite']
TEST_TEXT = 'Please subscribe to the channel. Investing involves risk; this is not financial advice.'


# ---------------------------------------------------------------------------
# Đọc / ghi cấu hình
# ---------------------------------------------------------------------------
def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def dub_cfg() -> dict:
    return read_json(DUB_CONFIG)


def set_dub_value(name: str, value: int) -> None:
    """Chỉ thay đúng 1 dòng, giữ nguyên định dạng + ghi chú của dub_all.config.json."""
    raw = DUB_CONFIG.read_text(encoding='utf-8')
    new, n = re.subn(rf'("{name}"\s*:\s*)-?\d+', rf'\g<1>{value}', raw, count=1)
    if n == 0:
        print(f'   [!] Không thấy "{name}" trong dub_all.config.json, bỏ qua.')
        return
    DUB_CONFIG.write_text(new, encoding='utf-8')


def get_keys(params: dict, channel: int) -> list:
    key_name = CHANNELS[channel]['key']
    if not key_name:
        return []
    return [k.strip() for k in str(params.get(key_name, '')).split(',') if k.strip()]


def set_model(channel: int, model: str) -> None:
    info = CHANNELS[channel]
    params = read_json(PARAMS_JSON)
    params[info['model']] = model
    write_json(PARAMS_JSON, params)
    # Đưa model lên đầu danh sách trong cfg.json, không thì ô chọn model trên giao diện
    # không có nó và bấm Lưu sẽ bị ghi đè bằng model đầu danh sách.
    cfg = read_json(CFG_JSON)
    if cfg:
        models = [m.strip() for m in str(cfg.get(info['model'], '')).split(',') if m.strip()]
        cfg[info['model']] = ','.join([model] + [m for m in models if m != model])
        write_json(CFG_JSON, cfg)


def current_model(params: dict, channel: int) -> str:
    model_key = CHANNELS.get(channel, {}).get('model')
    return str(params.get(model_key, '')) if model_key else '-'


def ninerouter_url(url: str) -> str:
    """Chuẩn hoá URL 9Router về dạng https://<tên miền>/v1 (giống videotrans/translator/_ninerouter.py)."""
    url = str(url or '').strip().strip('"').strip("'").rstrip('/')
    if not url:
        return ''
    if not url.startswith('http'):
        url = 'https://' + url
    url = re.sub(r'/chat/completions$', '', url)
    if not re.search(r'/v\d+$', url):
        url += '/v1'
    return url


def mask(key: str) -> str:
    return key if len(key) <= 12 else f'{key[:6]}…{key[-4:]}'


def proxy() -> str:
    return str(read_json(CFG_JSON).get('proxy', '') or '').strip()


# ---------------------------------------------------------------------------
# Tiện ích nhập liệu
# ---------------------------------------------------------------------------
def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ''


def ask_yes(prompt: str, default: bool = True) -> bool:
    hint = '[Y/n]' if default else '[y/N]'
    ans = ask(f'{prompt} {hint}: ').lower()
    return default if not ans else ans in ('y', 'yes', 'c', 'co', 'có')


def pause() -> None:
    ask('\n   Bấm Enter để quay lại menu...')


# ---------------------------------------------------------------------------
# Trạng thái
# ---------------------------------------------------------------------------
def show_status() -> None:
    cfg, params = dub_cfg(), read_json(PARAMS_JSON)
    t = int(cfg.get('translate_type', 0))
    name = CHANNELS.get(t, {}).get('name', f'translate_type={t}')
    print(f'   Kênh dịch đang dùng : {name}')
    if t in CHANNELS and CHANNELS[t]['model']:
        print(f'   Model               : {current_model(params, t)}')
        print(f'   Số API key          : {len(get_keys(params, t))}')
    if t == NINEROUTER:
        print(f'   URL 9Router         : {params.get("ninerouter_api") or "(chưa nhập)"}')
    print(f'   Dịch song song      : {cfg.get("translate_parallel", 4)} ngôn ngữ cùng lúc')


def after_switch(free: bool) -> None:
    parallel = int(dub_cfg().get('translate_parallel', PAID_PARALLEL))
    if free and parallel > FREE_PARALLEL:
        print('\n   Model miễn phí bị giới hạn số lượt/phút, dịch song song nhiều ngôn ngữ')
        print('   sẽ bị chặn lỗi 429 liên tục.')
        if ask_yes(f'   Đặt dịch song song = {FREE_PARALLEL} (dịch lần lượt từng ngôn ngữ)?'):
            set_dub_value('translate_parallel', FREE_PARALLEL)
    elif not free and parallel < PAID_PARALLEL:
        if ask_yes(f'   Đưa dịch song song về {PAID_PARALLEL} ngôn ngữ cùng lúc cho nhanh?'):
            set_dub_value('translate_parallel', PAID_PARALLEL)


def switch(channel: int, model: str | None, free: bool) -> None:
    set_dub_value('translate_type', channel)
    if model:
        set_model(channel, model)
    params = read_json(PARAMS_JSON)
    print(f'\n   ĐÃ ĐỔI sang: {CHANNELS[channel]["name"]}' + (f' · {model}' if model else ''))
    if CHANNELS[channel]['key'] and not get_keys(params, channel):
        print('   Kênh này chưa có API key nào.')
        if ask_yes('   Thêm key ngay bây giờ?'):
            add_keys(channel)
    after_switch(free)
    print('\n   Nên chạy mục 7 (Kiểm tra key + model) trước khi dịch thật.')


# ---------------------------------------------------------------------------
# Chọn model
# ---------------------------------------------------------------------------
def choose_openrouter_free() -> str | None:
    import httpx
    print('\n   Đang lấy danh sách model miễn phí từ OpenRouter...')
    try:
        resp = httpx.get('https://openrouter.ai/api/v1/models', timeout=30,
                         proxy=proxy() or None)
        resp.raise_for_status()
        models = sorted((m for m in resp.json().get('data', []) if m['id'].endswith(':free')),
                        key=lambda m: m['id'])
    except Exception as e:  # noqa: BLE001
        print(f'   Không lấy được danh sách ({e}).')
        models = []

    if models:
        kw = ask('   Gõ từ khoá để lọc (vd: gemini, deepseek, qwen) hoặc Enter để xem hết: ').lower()
        shown = [m for m in models if kw in m['id'].lower()] or models
        for i, m in enumerate(shown, 1):
            ctx = m.get('context_length') or 0
            print(f'   {i:>3}) {m["id"]:<55} ngữ cảnh {ctx // 1000}k')
        ans = ask('\n   Nhập số, hoặc gõ tên model, Enter để huỷ: ')
        if ans.isdigit() and 1 <= int(ans) <= len(shown):
            return shown[int(ans) - 1]['id']
    else:
        ans = ask('   Gõ tên model (vd: google/gemma-3-27b-it:free), Enter để huỷ: ')
    if not ans or ans.isdigit():
        return None
    if not ans.endswith(':free'):
        print('   [!] Tên model không có ":free" — model này sẽ TÍNH TIỀN.')
        if not ask_yes('   Vẫn dùng?', default=False):
            return None
    return ans


def choose_gemini() -> str | None:
    cfg = read_json(CFG_JSON)
    models = [m.strip() for m in str(cfg.get('gemini_model', '')).split(',') if m.strip()]
    models += [m for m in GEMINI_EXTRA_MODELS if m not in models]
    print()
    print('   Lưu ý: từ 28/05/2026 key Gemini mới (dạng AQ....) chỉ chạy khi project')
    print('   Google Cloud của key đó đã bật Billing (xem HUONG_DAN_LONG_TIENG.md).')
    print('   Key dạng AIza... cũ vẫn có thể dùng free tier. Hạn mức free tính theo')
    print('   PROJECT, nên nhiều key trong cùng 1 project không tăng thêm lượt.')
    print()
    for i, m in enumerate(models, 1):
        print(f'   {i:>3}) {m}')
    ans = ask('\n   Nhập số, hoặc gõ tên model khác, Enter để huỷ: ')
    if ans.isdigit() and 1 <= int(ans) <= len(models):
        return models[int(ans) - 1]
    return None if not ans or ans.isdigit() else ans


def choose_ninerouter() -> str | None:
    import httpx
    params = read_json(PARAMS_JSON)
    url = str(params.get('ninerouter_api', '') or '')
    print('\n   9Router gộp Claude / Gemini / DeepSeek / OpenRouter... thành 1 API.')
    print('   URL + key lấy ở mục "Endpoint & Key" trên dashboard 9Router.')
    ans = ask(f'   URL 9Router [Enter = {url or "chưa có"}]: ')
    if ans:
        url = ninerouter_url(ans)
    if not url:
        print('   Chưa có URL, huỷ.')
        return None
    params['ninerouter_api'] = url
    write_json(PARAMS_JSON, params)
    print(f'   URL: {url}')
    if not get_keys(params, NINEROUTER):
        print('   Chưa có key 9Router (dạng sk-...).')
        add_keys(NINEROUTER)
    keys = get_keys(read_json(PARAMS_JSON), NINEROUTER)

    print('\n   Đang lấy danh sách model từ 9Router...')
    models = []
    try:
        resp = httpx.get(f'{url}/models', timeout=30,
                         headers={'Authorization': f'Bearer {keys[0]}'} if keys else None)
        resp.raise_for_status()
        models = sorted({m['id'] for m in resp.json().get('data', []) if m.get('id')})
    except Exception as e:  # noqa: BLE001
        print(f'   Không lấy được danh sách ({e}).')

    if models:
        kw = ask('   Gõ từ khoá để lọc (vd: claude, gemini, deepseek) hoặc Enter để xem hết: ').lower()
        shown = [m for m in models if kw in m.lower()] or models
        for i, m in enumerate(shown, 1):
            print(f'   {i:>3}) {m}')
        print('\n   Chọn nhiều số theo thứ tự ưu tiên (vd: 2,15,30): model đầu bị lỗi')
        print('   404 / 429 / hết tiền thì phần mềm tự chuyển sang model tiếp theo.')
        ans = ask('   Nhập số, hoặc gõ tên model (nhiều model cách nhau dấu phẩy), Enter để huỷ: ')
        parts = [a for a in re.split(r'[\s,;]+', ans) if a]
        if parts and all(a.isdigit() for a in parts):
            picked = [shown[int(a) - 1] for a in parts if 1 <= int(a) <= len(shown)]
            return ','.join(dict.fromkeys(picked)) or None
    else:
        ans = ask('   Gõ tên model (nhiều model cách nhau dấu phẩy), Enter để huỷ: ')
    parts = [a for a in re.split(r'[\s,;]+', ans) if a]
    if not parts or any(a.isdigit() for a in parts):
        return None
    return ','.join(dict.fromkeys(parts))


# ---------------------------------------------------------------------------
# Quản lý key
# ---------------------------------------------------------------------------
def pick_channel(prompt: str) -> int | None:
    t = int(dub_cfg().get('translate_type', 0))
    options = KEY_CHANNELS
    print()
    for i, c in enumerate(options, 1):
        star = '  <- đang dùng' if c == t else ''
        print(f'   {i}) {CHANNELS[c]["name"]}{star}')
    default = options.index(t) + 1 if t in options else 1
    ans = ask(f'   {prompt} [Enter = {default}]: ') or str(default)
    if ans.isdigit() and 1 <= int(ans) <= len(options):
        return options[int(ans) - 1]
    return None


def add_keys(channel: int) -> None:
    info = CHANNELS[channel]
    print('\n   Dán key vào (có thể dán nhiều key, cách nhau dấu phẩy / dấu cách / xuống dòng).')
    print('   Bấm Enter ở dòng trống để kết thúc.')
    new = []
    while True:
        line = ask('   > ')
        if not line:
            break
        new += [k for k in re.split(r'[\s,;]+', line) if k]
    if not new:
        return
    params = read_json(PARAMS_JSON)
    keys = get_keys(params, channel)
    added = [k for k in dict.fromkeys(new) if k not in keys]
    for k in added:
        if info['prefix'] and not k.startswith(info['prefix']):
            print(f'   [!] {mask(k)} không giống key {info["name"]} '
                  f'(thường bắt đầu bằng {" hoặc ".join(info["prefix"])}). Vẫn thêm.')
    params[info['key']] = ','.join(keys + added)
    write_json(PARAMS_JSON, params)
    print(f'   Đã thêm {len(added)} key (bỏ {len(new) - len(added)} key trùng). '
          f'Tổng: {len(keys) + len(added)} key.')


def manage_keys() -> None:
    channel = pick_channel('Quản lý key của kênh nào?')
    if channel is None:
        return
    info = CHANNELS[channel]
    while True:
        keys = get_keys(read_json(PARAMS_JSON), channel)
        print(f'\n   --- Key của {info["name"]}: {len(keys)} key ---')
        for i, k in enumerate(keys, 1):
            print(f'   {i:>3}) {mask(k)}')
        print('\n   a) Thêm key    x) Xoá key    0) Quay lại')
        ans = ask('   Chọn: ').lower()
        if ans == 'a':
            add_keys(channel)
        elif ans == 'x' and keys:
            pick = ask('   Nhập số key cần xoá (vd: 2 hoặc 1,3), hoặc "all" để xoá hết: ').lower()
            if pick == 'all':
                drop = set(range(len(keys)))
            else:
                drop = {int(p) - 1 for p in re.split(r'[\s,]+', pick) if p.isdigit()}
            remain = [k for i, k in enumerate(keys) if i not in drop]
            if len(remain) != len(keys) and ask_yes(f'   Xoá {len(keys) - len(remain)} key?', False):
                params = read_json(PARAMS_JSON)
                params[info['key']] = ','.join(remain)
                write_json(PARAMS_JSON, params)
                print('   Đã xoá.')
        elif ans in ('0', ''):
            return


# ---------------------------------------------------------------------------
# Kiểm tra key + model
# ---------------------------------------------------------------------------
def explain_error(code, msg: str) -> str:
    msg = str(msg)
    if 'ACCESS_TOKEN_TYPE_UNSUPPORTED' in msg:
        return 'Key dạng AQ. cần project Google Cloud đã bật Billing.'
    if code == 429 or 'RESOURCE_EXHAUSTED' in msg:
        return 'Hết lượt / bị giới hạn tần suất. Chờ rồi thử lại, hoặc dùng key của tài khoản/project khác.'
    if code == 402:
        return 'Tài khoản hết tiền.'
    if code in (401, 403) or 'API key not valid' in msg:
        return 'Key sai, bị khoá hoặc đã bị xoá.'
    if code == 404:
        return 'Model không tồn tại hoặc không còn miễn phí.'
    if code == 400 and 'max' in msg.lower() and 'token' in msg.lower():
        return 'Max tokens quá lớn so với model này.'
    return ''


def test_one(channel: int, model: str, key: str, params: dict) -> tuple:
    prompt = f'Translate into French. Reply with the translation only.\n\n{TEST_TEXT}'
    started = time.time()
    if channel == GEMINI:
        from google import genai
        from google.genai import types, errors
        try:
            client = genai.Client(api_key=key, http_options=types.HttpOptions(
                client_args={'proxy': proxy() or None}))
            resp = client.models.generate_content(model=model, contents=prompt)
            return True, (resp.text or '').strip(), time.time() - started, None
        except errors.APIError as e:
            return False, f'{e.code} {e.message}', time.time() - started, e.code
    import httpx
    from openai import OpenAI, APIStatusError, APIConnectionError
    base = {OPENROUTER: 'https://openrouter.ai/api/v1',
            NINEROUTER: ninerouter_url(params.get('ninerouter_api', ''))}.get(channel, 'https://api.deepseek.com/v1')
    kwargs = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'timeout': 120}
    if channel in (OPENROUTER, NINEROUTER):
        prefix = 'openrouter' if channel == OPENROUTER else 'ninerouter'
        kwargs['max_tokens'] = int(float(params.get(f'{prefix}_max_token', 8192) or 8192))
        effort = params.get(f'{prefix}_reasoning_effort')
        if effort and effort != 'No':
            kwargs['reasoning_effort'] = effort
    else:
        kwargs['max_tokens'] = int(float(params.get('deepseek_max_token', 8192)))
    try:
        client = OpenAI(api_key=key, base_url=base,
                        http_client=httpx.Client(proxy=proxy() or None))
        resp = client.chat.completions.create(**kwargs)
        text = (resp.choices[0].message.content or '').strip() if resp.choices else ''
        if not text:
            reason = resp.choices[0].finish_reason if resp.choices else resp
            return False, f'trả về rỗng ({reason})', time.time() - started, None
        return True, text, time.time() - started, None
    except APIStatusError as e:
        body = e.body.get('message') if isinstance(e.body, dict) else e.message
        return False, f'{e.status_code} {body}', time.time() - started, e.status_code
    except APIConnectionError as e:
        return False, f'Không kết nối được: {e}', time.time() - started, None


def run_test() -> None:
    cfg, params = dub_cfg(), read_json(PARAMS_JSON)
    channel = int(cfg.get('translate_type', 0))
    if channel not in KEY_CHANNELS:
        print('\n   Kênh đang dùng không cần key, không có gì để kiểm tra.')
        return
    model, keys = current_model(params, channel), get_keys(params, channel)
    if not keys:
        print('\n   Chưa có key nào. Vào mục 6 để thêm.')
        return
    # Ô model có thể là chuỗi nhiều model (lỗi thì phần mềm chuyển model sau): kiểm tra từng cái
    models = [m.strip() for m in model.split(',') if m.strip()] or [model]
    if len(models) > 1:
        print(f'\n   Chuỗi model (lỗi thì tự chuyển sang model sau): {" -> ".join(models)}')
    for model in models:
        print(f'\n   Kiểm tra {CHANNELS[channel]["name"]} · {model} · {len(keys)} key')
        ok = 0
        for i, key in enumerate(keys, 1):
            good, text, secs, code = test_one(channel, model, key, params)
            status = 'OK ' if good else 'LỖI'
            print(f'\n   [{i}] {mask(key)} — {status} ({secs:.1f}s)')
            print(f'       {text[:300]}')
            if not good:
                hint = explain_error(code, text)
                if hint:
                    print(f'       => {hint}')
            ok += good
        print(f'\n   Kết quả {model}: {ok}/{len(keys)} key dùng được.')


# ---------------------------------------------------------------------------
# Dịch thử 1 file srt
# ---------------------------------------------------------------------------
def trial_translate() -> None:
    cfg, params = dub_cfg(), read_json(PARAMS_JSON)
    channel = int(cfg.get('translate_type', 0))
    source = cfg.get('source_language', 'en')
    raw = ask('\n   Kéo file .srt thả vào đây rồi Enter: ').strip('"').strip("'")
    srt = Path(raw).expanduser()
    if not raw or not srt.is_file():
        print('   Không thấy file.')
        return
    codes = [l['code'] for l in cfg.get('languages', [])]
    code = ask(f'   Dịch sang mã ngôn ngữ nào ({", ".join(codes)}) [Enter = ja]: ') or 'ja'

    model = current_model(params, channel) if CHANNELS.get(channel, {}).get('model') else 'google'
    # Chuỗi nhiều model: tên file lấy theo model đầu cho gọn
    slug = re.sub(r'[^A-Za-z0-9.-]+', '_', model.split(',')[0]).strip('_')
    out_dir = srt.parent / '_dich_thu'
    out_dir.mkdir(exist_ok=True)
    produced = out_dir / f'{srt.stem}.{code}.srt'
    produced.unlink(missing_ok=True)
    print(f'\n   Đang dịch {srt.name} -> {code} bằng {model} ...\n')
    started = time.time()
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    rc = subprocess.call([sys.executable, str(CLI_PY), '--task', 'sts', '--name', str(srt),
                          '--source_language_code', source, '--target_language_code', code,
                          '--translate_type', str(channel), '--output-dir', str(out_dir)],
                         cwd=str(ROOT_DIR), env=env)
    if rc == 0 and produced.exists() and produced.stat().st_size > 0:
        final = out_dir / f'{srt.stem}.{code}.{slug}.srt'
        produced.replace(final)
        print(f'\n   XONG sau {time.time() - started:.0f}s: {final}')
        print('   (Tên file có tên model, dịch thử nhiều model sẽ không ghi đè nhau để so sánh.)')
    else:
        print(f'\n   Dịch thử THẤT BẠI (mã lỗi {rc}). Xem thông báo ở trên, hoặc chạy mục 7.')


def set_parallel() -> None:
    now = dub_cfg().get('translate_parallel', PAID_PARALLEL)
    ans = ask(f'\n   Hiện tại: {now}. Nhập số mới (1 = lần lượt, 4 = mặc định): ')
    if ans.isdigit() and int(ans) >= 1:
        set_dub_value('translate_parallel', int(ans))
        print(f'   Đã đặt dịch song song = {ans}.')


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
def main() -> int:
    for path in (PARAMS_JSON, DUB_CONFIG):
        if not path.exists():
            print(f'[LỖI] Không thấy {path}')
            return 1
    while True:
        print()
        print('=' * 66)
        print('   ĐỔI KÊNH DỊCH / MODEL / API KEY')
        print('=' * 66)
        show_status()
        print('   (Đóng MO_PHAN_MEM và LONG_TIENG trước khi đổi để tránh bị ghi đè.)')
        print()
        print(f'   1) OpenRouter trả phí — {PAID_OPENROUTER_MODEL}  (mặc định)')
        print('   2) OpenRouter model MIỄN PHÍ (:free)')
        print('   3) Gemini — Google AI Studio (key free)')
        print('   4) DeepSeek chính hãng (dự phòng khi hết tiền OpenRouter)')
        print('   5) Google Dịch miễn phí (không cần key, chất lượng thấp hơn)')
        print('  10) 9Router trên VPS riêng (gộp Claude / Gemini / DeepSeek / OpenRouter)')
        print('   ' + '-' * 40)
        print('   6) Thêm / xoá API key (dán được nhiều key)')
        print('   7) Kiểm tra key + model đang dùng')
        print('   8) Dịch thử 1 file .srt sang 1 ngôn ngữ')
        print('   9) Đổi số ngôn ngữ dịch song song')
        print('   0) Thoát')
        choice = ask('\n   Nhập số rồi Enter: ')
        if choice in ('0', 'q'):
            return 0
        if choice == '1':
            switch(OPENROUTER, PAID_OPENROUTER_MODEL, free=False)
        elif choice == '2':
            model = choose_openrouter_free()
            if model:
                switch(OPENROUTER, model, free=True)
        elif choice == '3':
            model = choose_gemini()
            if model:
                switch(GEMINI, model, free=True)
        elif choice == '4':
            switch(DEEPSEEK, None, free=False)
        elif choice == '5':
            switch(GOOGLE, None, free=True)
        elif choice == '10':
            model = choose_ninerouter()
            if model:
                switch(NINEROUTER, model, free=False)
        elif choice == '6':
            manage_keys()
        elif choice == '7':
            run_test()
        elif choice == '8':
            trial_translate()
        elif choice == '9':
            set_parallel()
        else:
            continue
        pause()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
