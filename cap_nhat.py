# -*- coding: utf-8 -*-
"""
Cập nhật bộ lồng tiếng lên bản mới nhất trên GitHub (CAP_NHAT.bat).

Chỉ dùng thư viện chuẩn của Python, không cần cài Git.
  1. Hỏi GitHub commit mới nhất của nhánh main, so với file .phienban.
  2. Tải bản zip của commit đó, chép đè lên thư mục hiện tại.
     Không đụng tới: API key (videotrans/params.json), videotrans/cfg.json,
     update_token.txt, .venv, models, output... (những thứ này không có trên GitHub).
     dub_all.config.json được cập nhật nhưng giữ nguyên kênh dịch + số dịch song song
     mà máy này đã chọn bằng DOI_MODEL.bat.
  3. Xoá các file đã bị xoá trên GitHub.
  4. Nếu thư viện thay đổi (pyproject.toml / uv.lock) thì chạy uv sync.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
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

REPO = 'Hoduylongofficial/pyvideotrans-longtieng'
BRANCH = 'main'
API = f'https://api.github.com/repos/{REPO}'

ROOT_DIR = Path(__file__).resolve().parent
VERSION_FILE = ROOT_DIR / '.phienban'
TOKEN_FILE = ROOT_DIR / 'update_token.txt'
DUB_CONFIG = 'dub_all.config.json'
# Giá trị riêng của từng máy trong dub_all.config.json, giữ lại khi cập nhật
KEEP_DUB_VALUES = ('translate_type', 'translate_parallel')
# Không bao giờ ghi đè / xoá, kể cả khi lỡ có trên GitHub
PROTECTED = {'videotrans/params.json', 'videotrans/cfg.json', 'update_token.txt', '.phienban'}
PROTECTED_DIRS = ('.venv/', 'models/', 'output/', 'logs/', '.git/')
DEP_FILES = ('pyproject.toml', 'uv.lock')


class UpdateError(Exception):
    pass


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
def get_token() -> str:
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    if token:
        return token
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding='utf-8').strip()
        if token:
            return token
    print('   Máy này chưa có mã cập nhật (token GitHub). Xin quản lý rồi dán vào đây.')
    token = input('   Token: ').strip()
    if not token:
        raise UpdateError('Chưa nhập token.')
    TOKEN_FILE.write_text(token, encoding='utf-8')
    return token


def github(url: str, token: str, raw: bool = False):
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'pyvideotrans-longtieng-updater',
    })
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            raise UpdateError(
                f'GitHub từ chối ({e.code}). Token sai, hết hạn hoặc không có quyền đọc repo.\n'
                f'   Xin token mới từ quản lý, xoá file update_token.txt rồi chạy lại.') from e
        raise UpdateError(f'GitHub lỗi {e.code}: {e.reason}') from e
    except urllib.error.URLError as e:
        raise UpdateError(f'Không kết nối được GitHub: {e.reason}') from e
    return data if raw else json.loads(data)


def changes_since(old: str, new: str, token: str) -> tuple:
    """(danh sách commit message, danh sách file bị xoá, đủ thông tin hay không)."""
    try:
        cmp = github(f'{API}/compare/{old}...{new}', token)
    except UpdateError:
        return [], [], False
    messages = [c['commit']['message'].splitlines()[0] for c in cmp.get('commits', [])]
    removed = []
    for f in cmp.get('files', []):
        if f.get('status') == 'removed':
            removed.append(f['filename'])
        elif f.get('status') == 'renamed' and f.get('previous_filename'):
            removed.append(f['previous_filename'])
    # API chỉ trả tối đa 300 file; quá thì không tin được danh sách xoá
    complete = len(cmp.get('files', [])) < 300
    return messages, removed, complete


# ---------------------------------------------------------------------------
# Áp dụng bản cập nhật
# ---------------------------------------------------------------------------
def is_protected(rel: str) -> bool:
    return rel in PROTECTED or rel.startswith(PROTECTED_DIRS)


def file_hash(paths) -> str:
    # Bỏ qua khác biệt CRLF/LF: zip từ GitHub là LF, bản cài từ zip cũ có thể là CRLF
    h = hashlib.sha256()
    for p in paths:
        f = ROOT_DIR / p
        h.update(f.read_bytes().replace(b'\r\n', b'\n') if f.exists() else b'')
    return h.hexdigest()


def merge_dub_config(new_raw: str) -> str:
    """Lấy file cấu hình mới nhưng giữ kênh dịch / dịch song song đang dùng trên máy này."""
    local = ROOT_DIR / DUB_CONFIG
    if not local.exists():
        return new_raw
    old_raw = local.read_text(encoding='utf-8')
    for name in KEEP_DUB_VALUES:
        m = re.search(rf'"{name}"\s*:\s*(-?\d+)', old_raw)
        if m:
            new_raw = re.sub(rf'("{name}"\s*:\s*)-?\d+', rf'\g<1>{m.group(1)}', new_raw, count=1)
    return new_raw


def write_file(rel: str, data: bytes) -> bool:
    dest = ROOT_DIR / rel
    if dest.exists() and dest.read_bytes() == data:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + '.capnhat')
    tmp.write_bytes(data)
    try:
        os.replace(tmp, dest)
    except PermissionError as e:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f'Không ghi được {rel} (file đang mở?). '
                          f'Đóng MO_PHAN_MEM / LONG_TIENG rồi chạy lại.') from e
    return True


def apply_zip(blob: bytes) -> list:
    changed = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Bỏ thư mục gốc "<owner>-<repo>-<sha>/" trong zip của GitHub
            rel = info.filename.split('/', 1)[1] if '/' in info.filename else ''
            if not rel or is_protected(rel):
                continue
            data = zf.read(info)
            if rel == DUB_CONFIG:
                data = merge_dub_config(data.decode('utf-8')).encode('utf-8')
            if write_file(rel, data):
                changed.append(rel)
    return changed


def uv_sync() -> None:
    uv = shutil.which('uv')
    if not uv:
        print('   [!] Không thấy lệnh uv — hãy tự chạy "uv sync" trong thư mục này.')
        return
    print('\n   Thư viện có thay đổi, đang chạy uv sync (có thể mất vài phút)...\n')
    rc = subprocess.call([uv, 'sync'], cwd=str(ROOT_DIR))
    if rc != 0:
        raise UpdateError('uv sync lỗi. Kiểm tra mạng rồi chạy lại CAP_NHAT.bat.')


def main() -> int:
    print()
    print('=' * 62)
    print('   CẬP NHẬT BỘ LỒNG TIẾNG')
    print('=' * 62)
    try:
        token = get_token()
        print('   Đang kiểm tra bản mới trên GitHub...')
        latest = github(f'{API}/commits/{BRANCH}', token)
        new_sha = latest['sha']
        old_sha = VERSION_FILE.read_text(encoding='utf-8').strip() if VERSION_FILE.exists() else ''
        if old_sha == new_sha:
            print(f'\n   Đang là bản mới nhất ({new_sha[:7]}). Không cần cập nhật.')
            return 0

        messages, removed, complete = changes_since(old_sha, new_sha, token) if old_sha else ([], [], False)
        if messages:
            print(f'\n   Có {len(messages)} thay đổi mới:')
            for msg in messages[-20:]:
                print(f'     - {msg}')
        else:
            print(f'\n   Bản mới: {latest["commit"]["message"].splitlines()[0]}')

        deps_before = file_hash(DEP_FILES)
        print('\n   Đang tải bản mới...')
        blob = github(f'{API}/zipball/{new_sha}', token, raw=True)
        changed = apply_zip(blob)

        deleted = []
        if complete:
            for rel in removed:
                f = ROOT_DIR / rel
                if not is_protected(rel) and f.is_file():
                    f.unlink()
                    deleted.append(rel)

        print(f'   Đã cập nhật {len(changed)} file' + (f', xoá {len(deleted)} file.' if deleted else '.'))
        for rel in (changed + deleted)[:30]:
            print(f'     {rel}')
        if len(changed) + len(deleted) > 30:
            print(f'     ... và {len(changed) + len(deleted) - 30} file khác')

        if file_hash(DEP_FILES) != deps_before:
            uv_sync()

        VERSION_FILE.write_text(new_sha, encoding='utf-8')
        print(f'\n   XONG — đang ở bản {new_sha[:7]}.')
        return 0
    except UpdateError as e:
        print(f'\n   [LỖI] {e}')
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
