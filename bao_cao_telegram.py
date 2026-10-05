# -*- coding: utf-8 -*-
"""
Gửi báo cáo / log lỗi của LONG_TIENG.bat về nhóm Telegram (CAI_TELEGRAM.bat để cài).

dub_all.py gọi các hàm ở đây:
  - xong 1 lượt     : tin tóm tắt + report.md; có lỗi / cảnh báo thì gửi kèm file zip log
  - dừng vì lỗi     : tin báo lỗi + zip log (có traceback trong dub_all.log)
  - lượt trước bị ngắt (đóng cửa sổ, tắt máy, treo phải tắt): lần chạy sau tự gửi bù zip log

Token bot + ID nhóm nằm trong videotrans/params.json (telegram_bot_token, telegram_chat_id) —
không lên GitHub vì repo công khai. Gửi lỗi (mất mạng, sai token) chỉ cảnh báo, không bao giờ
làm hỏng lượt lồng tiếng.
"""
import json
import os
import socket
import sys
import time
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
PARAMS_JSON = ROOT_DIR / 'videotrans' / 'params.json'
CFG_JSON = ROOT_DIR / 'videotrans' / 'cfg.json'
API = 'https://api.telegram.org/bot{token}/{method}'
MAX_ZIP = 45 * 1024 * 1024  # Telegram bot gửi file tối đa 50 MB
# Dòng trong dub_all.log đánh dấu 1 lượt đã kết thúc đàng hoàng (không có = bị ngắt giữa chừng)
RUN_START = '  Video      : '
RUN_END = ('Hoàn tất sau', '[DỪNG]', '[LỖI]', '[Xem trước]')
# Dòng log cho thấy lượt chạy có vấn đề -> gửi kèm zip log dù cuối cùng không ngôn ngữ nào lỗi
TROUBLE = ('LỖI', '[CẢNH BÁO]', 'hỏng lần', 'treo ', 'hỏng nặng')


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def _settings() -> tuple:
    p = _read_json(PARAMS_JSON)
    return str(p.get('telegram_bot_token', '') or '').strip(), str(p.get('telegram_chat_id', '') or '').strip()


def configured() -> bool:
    return all(_settings())


def _proxies() -> dict:
    proxy = str(_read_json(CFG_JSON).get('proxy', '') or '').strip()
    return {'http': proxy, 'https': proxy} if proxy else {}


def _call(method: str, token: str = None, data: dict = None, files: dict = None, timeout: int = 60) -> dict:
    import requests
    token = token or _settings()[0]
    r = requests.post(API.format(token=token, method=method), data=data or {}, files=files,
                      timeout=timeout, proxies=_proxies())
    res = r.json()
    if not res.get('ok'):
        # Nhóm thường được Telegram nâng lên siêu nhóm -> đổi ID; tự cập nhật rồi gửi lại
        new_id = (res.get('parameters') or {}).get('migrate_to_chat_id')
        if new_id and data and 'chat_id' in data:
            _save(telegram_chat_id=str(new_id))
            for f in (files or {}).values():
                f.seek(0)
            return _call(method, token, {**data, 'chat_id': str(new_id)}, files, timeout)
        raise RuntimeError(res.get('description') or f'HTTP {r.status_code}')
    return res


def _save(**kv) -> None:
    p = _read_json(PARAMS_JSON)
    p.update(kv)
    tmp = PARAMS_JSON.with_suffix('.tmp')
    tmp.write_text(json.dumps(p, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, PARAMS_JSON)


def machine() -> str:
    try:
        user = os.getlogin()
    except OSError:
        user = os.environ.get('USERNAME', '?')
    return f'{socket.gethostname()} ({user})'


def send(text: str, files: list = ()) -> None:
    """Gửi 1 tin + các file (file đầu tiên mang chú thích nếu tin quá dài). Lỗi thì raise."""
    token, chat = _settings()
    _call('sendMessage', token, {'chat_id': chat, 'text': text[:4000], 'disable_web_page_preview': 'true'})
    for path in files:
        with open(path, 'rb') as fh:
            _call('sendDocument', token, {'chat_id': chat}, {'document': (Path(path).name, fh)}, timeout=300)


# ---------------------------------------------------------------------------
# Gói log
# ---------------------------------------------------------------------------
def zip_logs(workdir: Path, tag: str) -> Path:
    """dub_all.log + report.md + logs/* của 1 thư mục làm việc -> logs/_telegram/<tag>.zip."""
    files = [workdir / 'dub_all.log', workdir / 'report.md'] + \
        sorted(p for p in (workdir / 'logs').glob('*') if p.is_file())
    files = [p for p in files if p.exists()]
    out_dir = workdir / 'logs' / '_telegram'
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob('*.zip'):
        old.unlink(missing_ok=True)
    out = out_dir / f'log_{tag}_{time.strftime("%Y%m%d_%H%M%S")}.zip'
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(workdir).as_posix())
    if out.stat().st_size > MAX_ZIP:
        # Log cli.py quá to (hiếm): chỉ giữ log tổng + báo cáo soát lỗi
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                if p.suffix in ('.txt', '.md') or p.name == 'dub_all.log':
                    zf.write(p, p.relative_to(workdir).as_posix())
    return out


def last_run(logfile: Path) -> list:
    """Các dòng của lượt chạy gần nhất trong dub_all.log."""
    if not logfile.exists():
        return []
    lines = logfile.read_text(encoding='utf-8', errors='replace').splitlines()
    starts = [i for i, l in enumerate(lines) if RUN_START in l]
    return lines[starts[-1]:] if starts else []


def _video_of(lines: list) -> str:
    for l in lines:
        if RUN_START in l:
            return Path(l.split(RUN_START, 1)[1].strip()).name
    return '?'


# ---------------------------------------------------------------------------
# Gọi từ dub_all.py — không bao giờ raise
# ---------------------------------------------------------------------------
def _mode(cfg: dict) -> str:
    return str(cfg.get('telegram_notify', 'always')).strip().lower()


def _safe(log, what: str, fn) -> None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - gửi báo cáo lỗi không được làm hỏng lượt lồng tiếng
        if log:
            log(f'  [CẢNH BÁO] Không gửi được {what} lên Telegram ({e})')


def report_interrupted(cfg: dict, workdir: Path, lines: list, log=None) -> None:
    """lines = last_run() đọc TRƯỚC khi lượt mới ghi log: lượt trước không có dòng kết thúc = bị ngắt."""
    if _mode(cfg) == 'off' or not configured():
        return
    if not lines or any(m in l for l in lines for m in RUN_END):
        return
    last = lines[-1].strip()

    def go():
        send(f'⚠️ LƯỢT TRƯỚC BỊ NGẮT GIỮA CHỪNG\n'
             f'Video: {_video_of(lines)}\nMáy: {machine()}\n'
             f'(đóng cửa sổ / tắt máy / treo phải tắt — giờ đang chạy lại)\n\n'
             f'Dòng log cuối:\n{last}', [zip_logs(workdir, 'bi_ngat')])
    _safe(log, 'log lượt bị ngắt', go)


def report_done(cfg: dict, workdir: Path, video: Path, report: Path, summary: str, failed: list,
                log=None) -> None:
    mode = _mode(cfg)
    if mode == 'off' or not configured():
        return
    trouble = [l.split(' ', 1)[-1].strip() for l in last_run(workdir / 'dub_all.log')
               if any(t in l for t in TROUBLE)]
    if mode == 'errors' and not failed and not trouble:
        return
    icon = '❌' if failed else ('⚠️' if trouble else '✅')
    text = f'{icon} LỒNG TIẾNG XONG — {video.name}\nMáy: {machine()}\n{summary}'
    if failed:
        text += f'\nNgôn ngữ lỗi: {", ".join(failed)}'
    if trouble:
        text += '\n\nCần xem:\n' + '\n'.join(f'• {t}' for t in trouble[:15])
        if len(trouble) > 15:
            text += f'\n… và {len(trouble) - 15} dòng nữa (trong file zip)'
    files = [zip_logs(workdir, 'loi')] if failed or trouble else [report]
    _safe(log, 'báo cáo', lambda: send(text, files))


def report_crash(cfg: dict, workdir: Path, video: Path, error: str, log=None) -> None:
    if _mode(cfg) == 'off' or not configured():
        return
    _safe(log, 'báo lỗi', lambda: send(f'❌ LỒNG TIẾNG DỪNG VÌ LỖI — {video.name}\nMáy: {machine()}\n\n{error}',
                                        [zip_logs(workdir, 'crash')]))


# ---------------------------------------------------------------------------
# CAI_TELEGRAM.bat — cài token + nhóm
# ---------------------------------------------------------------------------
def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ''


def _mask(s: str) -> str:
    return s if len(s) <= 12 else f'{s[:6]}…{s[-4:]}'


def _find_groups(token: str) -> dict:
    """{chat_id: tên nhóm} từ các tin bot nhận được trong 24 giờ qua (lúc được thêm vào nhóm, /start...)."""
    groups = {}
    for u in _call('getUpdates', token).get('result', []):
        for key in ('message', 'my_chat_member', 'channel_post', 'edited_message'):
            chat = (u.get(key) or {}).get('chat') or {}
            if chat.get('type') in ('group', 'supergroup'):
                groups[str(chat['id'])] = chat.get('title', '')
    return groups


def setup() -> int:
    print('\n   GỬI BÁO CÁO / LOG LỖI LỒNG TIẾNG VỀ NHÓM TELEGRAM')
    print('   Token bot + ID nhóm lấy từ người quản trị.\n')
    token, chat = _settings()
    ans = _ask(f'   Token bot [Enter = {_mask(token) if token else "chưa có"}]: ').strip('"')
    token = ans or token
    if not token:
        print('   Chưa có token, huỷ.')
        return 1
    try:
        bot = _call('getMe', token)['result']['username']
    except Exception as e:  # noqa: BLE001
        print(f'   Token không dùng được: {e}')
        return 1
    print(f'   Bot: @{bot}')

    ans = _ask(f'   ID nhóm [Enter = {chat or "tự tìm"}]: ')
    if ans:
        chat = ans
    elif not chat:
        print(f'\n   Thêm @{bot} vào nhóm Telegram, gõ trong nhóm: /start@{bot}')
        _ask('   Xong thì bấm Enter...')
        try:
            groups = _find_groups(token)
        except Exception as e:  # noqa: BLE001
            print(f'   Không đọc được tin của bot: {e}')
            return 1
        if not groups:
            print('   Chưa thấy nhóm nào. Kiểm tra bot đã ở trong nhóm và đã gõ lệnh trên, rồi chạy lại.')
            return 1
        items = list(groups.items())
        for i, (cid, title) in enumerate(items, start=1):
            print(f'   {i}) {title}  (ID {cid})')
        pick = _ask('   Chọn nhóm [1]: ') or '1'
        if not pick.isdigit() or not 1 <= int(pick) <= len(items):
            print('   Chọn sai, huỷ.')
            return 1
        chat = items[int(pick) - 1][0]

    _save(telegram_bot_token=token, telegram_chat_id=chat)
    try:
        send(f'✅ Máy {machine()} đã bật gửi báo cáo lồng tiếng về nhóm này.')
    except Exception as e:  # noqa: BLE001
        print(f'   Đã lưu nhưng gửi thử thất bại: {e}')
        return 1
    print(f'\n   ĐÃ LƯU. Đã gửi tin thử vào nhóm (ID {chat}).')
    print('   Từ giờ mỗi lượt LONG_TIENG xong / lỗi / bị ngắt sẽ tự gửi báo cáo về nhóm.')
    return 0


if __name__ == '__main__':
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
    sys.exit(setup())
