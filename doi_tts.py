# -*- coding: utf-8 -*-
"""
Đổi giọng đọc (TTS) cho LONG_TIENG.bat (DOI_TTS.bat).

  1) Edge-TTS  : giọng Microsoft online, miễn phí, mỗi ngôn ngữ 1 giọng cố định
  2) OmniVoice : chạy trên GPU thuê của Modal (modal.com), nhái giọng — nhập URL + key
  3) Giọng mẫu : nhái từng câu từ video gốc, hoặc 1 file giọng mẫu cố định
  4) Đọc thử + ước tính thời gian / chi phí
  5) (Máy quản trị) deploy / cập nhật server trên Modal, tạo key

Ghi vào dub_all.config.json: "tts_type"; videotrans/params.json: omnivoice_modal_url,
omnivoice_modal_key, omnivoice_ref_wav, omnivoice_ref_text (params.json không lên GitHub).
"""
import base64
import io
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from doi_model import (DUB_CONFIG, PARAMS_JSON, ROOT_DIR, ask, ask_yes, dub_cfg, mask, pause,
                       read_json, set_dub_value, write_json)

EDGE_TTS, OMNIVOICE = 0, 3
TTS_NAMES = {EDGE_TTS: 'Edge-TTS (online, miễn phí)', OMNIVOICE: 'OmniVoice trên GPU thuê Modal'}
MODAL_APP = ROOT_DIR / 'modal_tts' / 'omnivoice_modal.py'
MODAL_SECRET = 'omnivoice-auth'
REF_DIR = ROOT_DIR / 'f5-tts'
REF_FILE = 'giong_mau_omnivoice.wav'
GPU_USD_PER_HOUR = 0.80          # Modal L4 (modal.com/pricing, 09/2026)
TEST_SENTENCES = ['Bine ați venit! Astăzi vorbim despre cum să începi tranzacționarea.',
                  'Nu risca niciodată mai mult de unu la sută pe tranzacție.',
                  'Exersează pe un cont demo înainte să folosești bani reali.',
                  'Folosește mereu un stop loss ca să-ți protejezi contul de pierderi mari.'] * 4
TEST_REF_TEXT = 'Welcome back to the channel. Today we are going to talk about trading for beginners.'


def params() -> dict:
    return read_json(PARAMS_JSON)


def save_params(**kv) -> None:
    p = params()
    p.update(kv)
    write_json(PARAMS_JSON, p)


def remote() -> tuple:
    p = params()
    return str(p.get('omnivoice_modal_url', '') or '').strip(), str(p.get('omnivoice_modal_key', '') or '').strip()


# ---------------------------------------------------------------------------
def show_status() -> None:
    t = int(dub_cfg().get('tts_type', EDGE_TTS))
    url, key = remote()
    p = params()
    print(f'   Giọng đọc đang dùng : {TTS_NAMES.get(t, f"tts_type={t}")}')
    print(f'   Server GPU Modal    : {url or "(chưa nhập)"}' + (f'  · key {mask(key)}' if key else ''))
    ref = str(p.get('omnivoice_ref_wav', '') or '')
    print(f'   Giọng mẫu OmniVoice : {"file cố định " + ref if ref else "nhái từng câu từ video gốc"}')


def use_edge() -> None:
    set_dub_value('tts_type', EDGE_TTS)
    print(f'\n   ĐÃ ĐỔI sang: {TTS_NAMES[EDGE_TTS]}')


def check_server(url: str, key: str) -> bool:
    import requests
    print('   Kiểm tra server (lần đầu GPU khởi động mất ~30 giây)...')
    try:
        if requests.get(url.rstrip('/') + '/health', timeout=300).status_code != 200:
            print('   Server không trả lời đúng. Kiểm tra lại URL.')
            return False
        r = requests.post(url.rstrip('/') + '/tts', json={'items': []}, timeout=60,
                          headers={'Authorization': f'Bearer {key}'})
    except Exception as e:  # noqa: BLE001
        print(f'   Không kết nối được: {e}')
        return False
    if r.status_code == 401:
        print('   SAI KEY.')
        return False
    print('   Kết nối OK.')
    return True


def use_omnivoice() -> None:
    url, key = remote()
    print('\n   OmniVoice chạy trên GPU thuê của Modal: máy này không cần card đồ hoạ.')
    print('   URL + key lấy từ người quản trị (máy quản trị chạy mục 5 để tạo).')
    ans = ask(f'   URL server [Enter = {url or "chưa có"}]: ').strip().strip('"').rstrip('/')
    if ans:
        url = ans if ans.startswith('http') else 'https://' + ans
    ans = ask(f'   Key [Enter = {mask(key) if key else "chưa có"}]: ').strip().strip('"')
    if ans:
        key = ans
    if not url or not key:
        print('   Thiếu URL hoặc key, huỷ.')
        return
    if not check_server(url, key) and not ask_yes('   Vẫn lưu?', default=False):
        return
    save_params(omnivoice_modal_url=url, omnivoice_modal_key=key)
    set_dub_value('tts_type', OMNIVOICE)
    print(f'\n   ĐÃ ĐỔI sang: {TTS_NAMES[OMNIVOICE]}')
    print('   Nên chạy mục 4 (đọc thử) trước khi làm cả loạt.')


def choose_ref() -> None:
    print('\n   Giọng mẫu cho OmniVoice:')
    print('   1) Nhái từng câu từ video gốc — mỗi câu lấy đúng câu tiếng Anh gốc làm mẫu (mặc định)')
    print('   2) 1 file giọng mẫu cố định — giọng đều, chuẩn nhất. File 5-15 giây, 1 người nói,')
    print('      không nhạc nền (wav/mp3/m4a). Mọi ngôn ngữ đều đọc bằng giọng này.')
    c = ask('   Chọn: ')
    if c == '1':
        save_params(omnivoice_ref_wav='', omnivoice_ref_text='')
        print('   Đã chọn: nhái từng câu từ video gốc.')
        return
    if c != '2':
        return
    raw = ask('   Kéo file giọng mẫu thả vào đây rồi Enter: ').strip().strip('"').strip("'")
    src = Path(raw)
    if not raw or not src.is_file():
        print('   Không thấy file.')
        return
    REF_DIR.mkdir(exist_ok=True)
    dest = REF_DIR / REF_FILE
    # OmniVoice nhái tốt nhất với mẫu 3-15 giây: cắt ở chỗ ngắt câu cuối cùng trong khoảng 6-15 giây
    probe = subprocess.run(['ffmpeg', '-hide_banner', '-t', '16', '-i', str(src), '-af',
                            'silencedetect=noise=-35dB:d=0.3', '-f', 'null', '-'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    cuts = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', probe) if 6 <= float(x) <= 15]
    length = (cuts[-1] + 0.2) if cuts else 15
    # Ghi ra file tạm rồi mới thay: người dùng có thể kéo thả chính file giọng mẫu đang dùng
    tmp = REF_DIR / (REF_FILE + '.tmp.wav')
    rc = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(src), '-t', f'{length:.2f}',
                         '-ac', '1', '-ar', '24000', str(tmp)]).returncode
    print(f'   Lấy {length:.1f} giây đầu của file làm giọng mẫu.')
    if rc != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        print('   Không đọc được file âm thanh này.')
        return
    tmp.replace(dest)
    print(f'   Gõ CHÍNH XÁC lời nói trong {length:.1f} giây đầu đó (giúp nhái giọng chuẩn hơn).')
    text = ask('   Enter để bỏ trống — server tự nghe ra lời (lần đầu chậm thêm ~1 phút): ')
    save_params(omnivoice_ref_wav=f'f5-tts/{REF_FILE}', omnivoice_ref_text=text)
    print(f'   Đã lưu giọng mẫu: {dest}')


def trial() -> None:
    import requests
    import soundfile as sf
    url, key = remote()
    if not url or not key:
        print('\n   Chưa có URL + key. Chạy mục 2 trước.')
        return
    p = params()
    out_dir = ROOT_DIR / 'tmp' / 'thu_omnivoice'
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = str(p.get('omnivoice_ref_wav', '') or '')
    if ref:
        ref_path, ref_text = ROOT_DIR / ref if not Path(ref).is_absolute() else Path(ref), p.get('omnivoice_ref_text', '')
        print(f'\n   Giọng mẫu: {ref_path}')
    else:
        # Không có file mẫu: tạm dùng 1 câu tiếng Anh của Edge-TTS làm giọng mẫu
        import asyncio, edge_tts
        ref_path, ref_text = out_dir / 'ref.wav', TEST_REF_TEXT
        asyncio.run(edge_tts.Communicate(TEST_REF_TEXT, 'en-US-AndrewNeural').save(str(out_dir / 'ref.mp3')))
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(out_dir / 'ref.mp3'),
                        '-ar', '24000', '-ac', '1', str(ref_path)], check=True)
        print('\n   Giọng mẫu: tạm dùng 1 câu tiếng Anh (khi lồng tiếng thật sẽ nhái giọng trong video)')
    sys.path.insert(0, str(ROOT_DIR))
    from videotrans.tts._omnivoice_modal import _encode_ref
    body = {'refs': {'r1': {'audio': _encode_ref(str(ref_path)), 'text': ref_text}},
            'items': [{'text': s, 'ref': 'r1', 'language': 'ro'} for s in TEST_SENTENCES]}
    print(f'   Gửi {len(TEST_SENTENCES)} câu tiếng Romania lên GPU Modal (lần đầu GPU khởi động ~30 giây)...')
    started = time.time()
    try:
        r = requests.post(url + '/tts', json=body, timeout=900, headers={'Authorization': f'Bearer {key}'})
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f'   THẤT BẠI: {e}')
        return
    total = time.time() - started
    data = r.json()
    for i, a in enumerate(data['audios'][:4], 1):
        wav, sr = sf.read(io.BytesIO(base64.b64decode(a)))
        sf.write(str(out_dir / f'thu_{i}.wav'), wav, sr)
    per = data['seconds'] / len(TEST_SENTENCES)
    lines, n_langs = 257, len(dub_cfg().get('languages', [])) or 25
    # Tính tiền theo thời gian máy GPU bật: phần đọc + ~5 giây mạng mỗi lượt 32 câu
    per_lang_s = lines * per + (lines / 32) * 5
    print(f'\n   GPU đọc {data["seconds"]}s cho {len(TEST_SENTENCES)} câu (~{per:.2f}s/câu), cả lượt {total:.0f}s.')
    print(f'   Ước tính 1 video {lines} câu: ~{per_lang_s / 60:.0f} phút/ngôn ngữ, '
          f'~{per_lang_s * n_langs / 60:.0f} phút cho {n_langs} ngôn ngữ, '
          f'chi phí GPU ~{per_lang_s * n_langs / 3600 * GPU_USD_PER_HOUR:.2f} USD.')
    print(f'   Nghe thử: {out_dir}')


# ---------------------------------------------------------------------------
def _modal(*args, capture=False):
    cmd = ['uvx', '--from', 'modal', 'modal', *args]
    # Khi bắt output qua pipe, Python của modal CLI mặc định ghi bằng cp1252 và chết ở ký tự '✓'
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
    if capture:
        return subprocess.run(cmd, cwd=str(ROOT_DIR), env=env, capture_output=True, text=True,
                              encoding='utf-8', errors='replace')
    return subprocess.run(cmd, cwd=str(ROOT_DIR), env=env)


def admin_deploy() -> None:
    print('\n   DEPLOY SERVER OMNIVOICE LÊN MODAL (chỉ máy quản trị)')
    if not shutil.which('uvx'):
        print('   Cần cài uv trước: https://docs.astral.sh/uv/')
        return
    if not (Path.home() / '.modal.toml').exists():
        print('   Máy này chưa đăng nhập Modal: trình duyệt sẽ mở, bấm xác nhận trong trang Modal.')
        if _modal('token', 'new').returncode != 0:
            return
    url, key = remote()
    if not key or ask_yes('   Tạo key MỚI? (key cũ trên máy nhân viên sẽ hết dùng được)', default=False):
        key = secrets.token_urlsafe(32)
        r = _modal('secret', 'create', '--force', MODAL_SECRET, f'OMNIVOICE_API_KEY={key}', capture=True)
        if r.returncode != 0:
            print('   Tạo secret THẤT BẠI:', (r.stdout + r.stderr).replace(key, '***')[-500:])
            return
        save_params(omnivoice_modal_key=key)
        print('   Đã tạo key mới.')
    print('   Đang deploy (lần đầu ~3 phút)...')
    r = _modal('deploy', str(MODAL_APP), capture=True)
    out = r.stdout + r.stderr
    found = re.findall(r'https://\S+\.modal\.run', out)
    if r.returncode != 0 or not found:
        print('   Deploy THẤT BẠI:\n' + out[-1500:])
        return
    save_params(omnivoice_modal_url=found[-1])
    print(f'\n   DEPLOY XONG. URL: {found[-1]}')
    if ask_yes('   Hiện key để gửi cho nhân viên (gửi riêng, KHÔNG đăng nhóm chung)?', default=False):
        print(f'   Key: {key}')


# ---------------------------------------------------------------------------
def main() -> int:
    if not DUB_CONFIG.exists():
        print(f'[LỖI] Không thấy {DUB_CONFIG}')
        return 1
    while True:
        print()
        print('=' * 66)
        print('   ĐỔI GIỌNG ĐỌC (TTS)')
        print('=' * 66)
        show_status()
        print('   (Đóng LONG_TIENG trước khi đổi.)')
        print()
        print('   1) Edge-TTS — giọng Microsoft online, miễn phí  (mặc định)')
        print('   2) OmniVoice trên GPU thuê Modal — nhái giọng (nhập URL + key)')
        print('   3) Chọn giọng mẫu cho OmniVoice (nhái từng câu / 1 file giọng cố định)')
        print('   4) Đọc thử OmniVoice + ước tính thời gian, chi phí')
        print('   ' + '-' * 40)
        print('   5) [Máy quản trị] Deploy / cập nhật server trên Modal, tạo key')
        print('   0) Thoát')
        choice = ask('\n   Nhập số rồi Enter: ')
        if choice in ('0', 'q'):
            return 0
        actions = {'1': use_edge, '2': use_omnivoice, '3': choose_ref, '4': trial, '5': admin_deploy}
        if choice in actions:
            actions[choice]()
            pause()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
