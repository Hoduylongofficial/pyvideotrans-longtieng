#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
dub_all.py — Lồng tiếng hàng loạt nhiều ngôn ngữ từ 1 video + 1 file phụ đề gốc.

Chỉ cần cung cấp video và file SRT ngôn ngữ gốc, công cụ sẽ tự động:
  Pha 1  dịch phụ đề ra toàn bộ ngôn ngữ đích  (cli.py --task sts)
  Pha 2  lồng tiếng + nhúng phụ đề cứng + render  (cli.py --task vtv)

Nhờ truyền sẵn --source_srt / --target_srt cho cli.py, cả hai bước nhận dạng giọng nói
(Whisper) và dịch lại đều bị bỏ qua ở pha 2.

Ví dụ:
  uv run dub_all.py --video "D:/work/video.mp4" --srt "D:/work/en.srt"
  uv run dub_all.py --video "D:/work/video.mp4" --srt "D:/work/en.srt" --preview-styles
  uv run dub_all.py --video "D:/work/video.mp4" --srt "D:/work/en.srt" --langs ar,fi,da
  uv run dub_all.py --video "D:/work/video.mp4" --srt "D:/work/en.srt" --only translate

Cấu hình giọng đọc / kênh dịch / style phụ đề: dub_all.config.json
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        _disable_quick_edit()
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


def _disable_quick_edit() -> None:
    """Tắt QuickEdit của cửa sổ cmd: lỡ bấm chuột vào cửa sổ là console vào chế độ bôi đen, mọi print()
    đứng im tới khi bấm phím -> cả loạt dừng theo (luồng đang ghi log giữ khoá, cli.py nghẽn ống ra).
    Log máy nhân viên 10/2026: dịch xong fi.srt mà dòng "xong" không bao giờ ra, render sv đứng 73 phút."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # bỏ ENABLE_QUICK_EDIT_MODE (0x40); ENABLE_EXTENDED_FLAGS (0x80) bắt buộc để cờ đó có hiệu lực
            kernel32.SetConsoleMode(handle, (mode.value & ~0x0040) | 0x0080)
    except Exception:  # noqa: BLE001 - stdin không phải console (chạy nền / chuyển hướng)
        pass


_force_utf8_console()

ROOT_DIR = Path(__file__).resolve().parent
CLI_PY = ROOT_DIR / 'cli.py'
DEFAULT_CONFIG = ROOT_DIR / 'dub_all.config.json'
EDGE_VOICE_JSON = ROOT_DIR / 'videotrans' / 'voicejson' / 'edge_tts.json'
PARAMS_JSON = ROOT_DIR / 'videotrans' / 'params.json'

EDGE_TTS = 0
OMNIVOICE_TTS = 3
TTS_LABELS = {EDGE_TTS: 'Edge-TTS', OMNIVOICE_TTS: 'OmniVoice (GPU thuê Modal, nhái giọng)'}
VIDEO_EXTS = ('.mp4', '.mkv', '.mov', '.webm', '.avi')
# Giữ đồng bộ với videotrans.configure.contants.CJK_LANG
CJK_LANG = ('zh', 'ja', 'ko', 'yu', 'th', 'km', 'yue')

# Câu mẫu dùng cho --preview-styles khi chưa có phụ đề đã dịch
SAMPLE_TEXT = {
    "en": "This is a subtitle sample for a long YouTube video.",
    "ar": "هذا نموذج ترجمة لفيديو يوتيوب طويل.",
    "de": "Dies ist ein Untertitelbeispiel für ein langes YouTube-Video.",
    "es": "Este es un ejemplo de subtítulos para un vídeo largo de YouTube.",
    "fr": "Ceci est un exemple de sous-titres pour une longue vidéo YouTube.",
    "it": "Questo è un esempio di sottotitoli per un lungo video di YouTube.",
    "ja": "これは長いYouTube動画の字幕サンプルです。",
    "ko": "이것은 긴 유튜브 영상의 자막 샘플입니다.",
    "pt": "Este é um exemplo de legenda para um vídeo longo do YouTube.",
    "ru": "Это пример субтитров для длинного видео на YouTube.",
    "tr": "Bu, uzun bir YouTube videosu için altyazı örneğidir.",
    "hi": "यह एक लंबे यूट्यूब वीडियो के लिए सबटाइटल का नमूना है।",
    "zh-tw": "這是長篇 YouTube 影片的字幕範例。",
    "id": "Ini adalah contoh subtitle untuk video YouTube yang panjang.",
    "nl": "Dit is een voorbeeld van ondertiteling voor een lange YouTube-video.",
    "pl": "To jest przykład napisów do długiego filmu na YouTube.",
    "sv": "Detta är ett exempel på undertexter för en lång YouTube-video.",
    "ro": "Acesta este un exemplu de subtitrare pentru un videoclip YouTube lung.",
    "uk": "Це приклад субтитрів для довгого відео на YouTube.",
    "fi": "Tämä on tekstitysnäyte pitkää YouTube-videota varten.",
    "da": "Dette er et eksempel på undertekster til en lang YouTube-video.",
    "fil": "Ito ay isang halimbawa ng subtitle para sa mahabang video sa YouTube.",
    "ms": "Ini ialah contoh sari kata untuk video YouTube yang panjang.",
    "el": "Αυτό είναι ένα δείγμα υποτίτλων για ένα μεγάλο βίντεο στο YouTube.",
    "cs": "Toto je ukázka titulků pro dlouhé video na YouTube.",
}


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------
class Log:
    """Ghi ra màn hình và đồng thời vào file log tổng."""

    def __init__(self, logfile: Path):
        self.logfile = logfile
        self.logfile.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.logfile.open('a', encoding='utf-8')
        self._lock = threading.Lock()
        self.last = time.monotonic()
        self._closed = threading.Event()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def __call__(self, msg: str = "") -> None:
        stamp = time.strftime('%H:%M:%S')
        # pha dịch chạy nhiều luồng cùng lúc, không khoá thì các dòng log chèn lẫn vào nhau.
        # Ghi file trước: màn hình có đứng (bôi đen cửa sổ) thì file log vẫn đúng tiến độ thật
        with self._lock:
            self.fh.write(f'{stamp} {msg}\n')
            self.fh.flush()
            print(msg, flush=True)
            self.last = time.monotonic()

    def touch(self) -> None:
        """Màn hình vừa có dòng mới (output cli.py in thẳng, không qua log)."""
        self.last = time.monotonic()

    def _heartbeat(self) -> None:
        """Màn hình im vài phút (render cuối ~4-5 phút không in gì, dịch lại 1 ngôn ngữ ~4 phút) thì
        nhân viên tưởng treo và tắt cửa sổ: log máy nhân viên 10/2026 tắt giữa lúc đang render Hà Lan
        bình thường. Chỉ in ra màn hình, không ghi file log."""
        while not self._closed.wait(30):
            idle = time.monotonic() - self.last
            if idle >= HEARTBEAT_SECONDS:
                with self._lock:
                    print(f'    ... vẫn đang chạy ({int(idle // 60)} phút chưa có dòng mới) — '
                          f'ĐỪNG tắt cửa sổ, đừng bấm chuột vào cửa sổ', flush=True)
                    self.last = time.monotonic()

    def close(self) -> None:
        self._closed.set()
        self.fh.close()


HEARTBEAT_SECONDS = 120


def keep_awake() -> None:
    """Không cho Windows tự ngủ khi đang chạy (cả loạt ~1-2 giờ, máy văn phòng hay đặt ngủ sau 15-30 phút
    không đụng chuột). Tự hết hiệu lực khi chương trình thoát. Gập nắp laptop thì vẫn ngủ."""
    if sys.platform == 'win32':
        try:
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception:  # noqa: BLE001
            pass


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f'{h}h{m:02d}m{s:02d}s' if h else f'{m}m{s:02d}s'


# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------
def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f'[LỖI] Không tìm thấy file cấu hình: {path}')
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError as e:
        sys.exit(f'[LỖI] File cấu hình {path} không phải JSON hợp lệ: {e}')


def is_cjk(code: str) -> bool:
    return code[:2] in CJK_LANG


def style_for(cfg: dict, code: str) -> dict:
    """Trộn style nền + font theo hệ chữ + ghi đè riêng của ngôn ngữ."""
    sub = cfg.get('subtitle_style', {})
    style = dict(sub.get('base', {}))
    fonts = sub.get('fonts', {})
    style['Fontname'] = fonts.get(code) or fonts.get(code[:2]) or fonts.get('default', 'Arial')
    override = (sub.get('overrides') or {}).get(code)
    if isinstance(override, dict):
        style.update(override)
    return style


def maxlen_for(cfg: dict, code: str) -> int:
    """Số ký tự tối đa mỗi dòng phụ đề, ưu tiên giá trị đặt riêng cho từng ngôn ngữ.

    Tra theo thứ tự mã đầy đủ -> mã 2 ký tự -> cjk/default, giống cách chọn font.
    Cần thiết vì CJK_LANG gộp cả tiếng Thái, nhưng chữ Thái hẹp gần bằng chữ Latin
    chứ không vuông như chữ Hán, để 15 thì dòng ngắn và gãy vụn.
    """
    lengths = cfg.get('subtitle_style', {}).get('maxlen', {})
    for key in (code, code[:2]):
        if key in lengths:
            return int(lengths[key])
    return int(lengths.get('cjk', 15) if is_cjk(code) else lengths.get('default', 36))


def find_output_video(folder: Path, stem: str) -> Path | None:
    for ext in VIDEO_EXTS:
        candidate = folder / f'{stem}{ext}'
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def final_stem(lang: dict, video_stem: str) -> str:
    """Tên file thành phẩm: 'Tây Ban Nha (es) - ten video'. Kèm mã để đối chiếu subs/."""
    name = lang.get('name') or lang['code']
    name = re.sub(r'[\\/:*?"<>|]', '-', name).strip()
    return f'{name} ({lang["code"]}) - {video_stem}'


def find_final_video(final_dir: Path, lang: dict, video_stem: str) -> Path | None:
    return find_output_video(final_dir, final_stem(lang, video_stem))


# ---------------------------------------------------------------------------
# Kiểm tra đầu vào — dừng sớm với danh sách lỗi rõ ràng
# ---------------------------------------------------------------------------
def installed_font_families() -> set:
    """Đọc danh sách font từ registry Windows. Trả về set rỗng nếu không đọc được."""
    families = set()
    if sys.platform != 'win32':
        return families
    try:
        import winreg
    except ImportError:
        return families
    key_path = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    name = winreg.EnumValue(key, i)[0]
                    # "Segoe UI Bold (TrueType)" / "MS Gothic & MS PGothic (TrueType)"
                    name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
                    for part in name.split('&'):
                        families.add(part.strip().lower())
        except OSError:
            continue
    return families


def validate(cfg: dict, langs: list, video: Path, srt: Path, log: Log) -> None:
    errors, warnings = [], []

    if not video.exists():
        errors.append(f'Không tìm thấy video: {video}')
    if not srt.exists():
        errors.append(f'Không tìm thấy file phụ đề: {srt}')
    if not CLI_PY.exists():
        errors.append(f'Không tìm thấy {CLI_PY}')
    if not shutil.which('ffmpeg'):
        errors.append('Không tìm thấy ffmpeg trong PATH.')

    # Mã ngôn ngữ phải có trong bảng mã của pyvideotrans
    try:
        from videotrans.translator._lang_codes import LANGNAME_DICT
    except Exception as e:  # noqa: BLE001 - chỉ để báo lỗi thân thiện
        errors.append(f'Không import được bảng mã ngôn ngữ của pyvideotrans: {e}')
        LANGNAME_DICT = {}
    source_language = cfg.get('source_language', 'en')
    for code in [source_language] + [l['code'] for l in langs]:
        if LANGNAME_DICT and code not in LANGNAME_DICT:
            errors.append(f'Mã ngôn ngữ "{code}" không có trong pyvideotrans '
                          f'(xem: uv run cli.py --list languages)')

    # Giọng đọc phải tồn tại trong danh sách Edge-TTS
    if int(cfg.get('tts_type', EDGE_TTS)) == EDGE_TTS:
        voices = json.loads(EDGE_VOICE_JSON.read_text(encoding='utf-8-sig'))
        for lang in langs:
            pool = voices.get(lang['code'].split('-')[0], {})
            if lang['voice'] not in pool.values():
                errors.append(f'[{lang["code"]}] giọng đọc "{lang["voice"]}" '
                              f'không có trong Edge-TTS')
    elif int(cfg.get('tts_type')) == OMNIVOICE_TTS:
        params = json.loads(PARAMS_JSON.read_text(encoding='utf-8-sig'))
        if not (str(params.get('omnivoice_modal_url', '')).strip() and str(params.get('omnivoice_modal_key', '')).strip()):
            errors.append('OmniVoice chưa có URL + key GPU Modal. Nhập bằng DOI_TTS.bat mục 2.')
        ref = str(params.get('omnivoice_ref_wav', '') or '').strip()
        if ref and not (Path(ref) if Path(ref).is_absolute() else ROOT_DIR / ref).is_file():
            errors.append(f'Không thấy file giọng mẫu OmniVoice: {ref}. Chọn lại bằng DOI_TTS.bat mục 3.')

    # Font — chỉ cảnh báo, fontconfig vẫn có thể thay thế được
    families = installed_font_families()
    if families:
        for font in {style_for(cfg, l['code'])['Fontname'] for l in langs}:
            # Registry chỉ ghi tên biến thể, ví dụ "Yu Gothic UI" chỉ có ở dạng
            # "Yu Gothic UI Regular"/"Yu Gothic UI Bold", nên so khớp theo tiền tố
            if not any(f == font.lower() or f.startswith(font.lower() + ' ') for f in families):
                warnings.append(f'Font "{font}" không thấy cài trên máy, '
                                f'ffmpeg sẽ thay bằng font khác. Hãy kiểm tra --preview-styles.')

    # Kênh dịch cần API key
    translate_type = int(cfg.get('translate_type', 0))
    if any(l['code'] != source_language for l in langs):
        try:
            from videotrans.translator._registry import _ID_NAME_DICT
            provider = _ID_NAME_DICT.get(translate_type)
            if provider and provider.key_name:
                params = json.loads(PARAMS_JSON.read_text(encoding='utf-8-sig'))
                if not str(params.get(provider.key_name, '')).strip():
                    errors.append(f'Kênh dịch "{provider.name}" (translate_type={translate_type}) '
                                  f'chưa có "{provider.key_name}" trong videotrans/params.json')
        except Exception as e:  # noqa: BLE001
            warnings.append(f'Không kiểm tra được API key của kênh dịch: {e}')

    for msg in warnings:
        log(f'  [CẢNH BÁO] {msg}')
    if errors:
        log('')
        log('[DỪNG] Cấu hình chưa hợp lệ:')
        for msg in errors:
            log(f'  - {msg}')
        sys.exit(1)


# ---------------------------------------------------------------------------
# Chạy cli.py
# ---------------------------------------------------------------------------
_SRT_INDEX = re.compile(r'^\s*\d+\s*$')
STALLED_RC = -999  # run_cli trả về mã này khi phải giết tiến trình vì treo


def _kill_tree(proc: subprocess.Popen) -> None:
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.kill()


def run_cli(cli_args: list, log: Log, task_log: Path, env: dict | None = None,
            quiet: bool = False, stall_timeout: float | None = None) -> int:
    """Chạy cli.py, ghi toàn bộ output vào task_log, chỉ hiện dòng có ích lên màn hình.

    quiet=True: chỉ ghi vào task_log, không in ra màn hình. Dùng khi dịch song song
    nhiều ngôn ngữ, vì output của các tiến trình sẽ chèn lẫn vào nhau không đọc được.

    stall_timeout: số giây không có dòng output nào thì coi là treo (API không trả lời),
    giết tiến trình và trả về STALLED_RC để attempt() chạy lại.
    """
    cmd = [sys.executable, str(CLI_PY)] + cli_args
    run_env = os.environ.copy()
    run_env['PYTHONIOENCODING'] = 'utf-8'
    if env:
        run_env.update(env)

    skip_lines = 0  # nuốt phần thân của khối SRT được in ra khi tái dùng phụ đề
    with task_log.open('a', encoding='utf-8') as fh:
        fh.write(f'\n$ {" ".join(cli_args)}\n')
        proc = subprocess.Popen(cmd, cwd=str(ROOT_DIR), env=run_env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
                                bufsize=1)
        last_output = [time.monotonic()]
        stalled = threading.Event()

        def watchdog():
            while proc.poll() is None:
                if time.monotonic() - last_output[0] > stall_timeout:
                    stalled.set()
                    _kill_tree(proc)
                    return
                time.sleep(5)

        if stall_timeout:
            threading.Thread(target=watchdog, daemon=True).start()
        for line in proc.stdout:
            last_output[0] = time.monotonic()
            fh.write(line)
            if quiet:
                continue
            text = line.rstrip()
            if '-->' in text:
                skip_lines = 2
                continue
            if skip_lines > 0:
                skip_lines -= 1
                continue
            if not text or _SRT_INDEX.match(text):
                continue
            print(f'    {text}', flush=True)
            log.touch()
        proc.wait()
        if stalled.is_set():
            fh.write(f'\n[dub_all] {int(stall_timeout)}s không có output — đã dừng tiến trình vì treo\n')
            return STALLED_RC
    return proc.returncode


def attempt(cfg: dict, log: Log, head: str, task_log: Path, cli_args: list,
            succeeded, env: dict | None = None, quiet: bool = False,
            stall_timeout: float | None = None) -> bool:
    """Chạy cli.py, thử lại vài lần nếu hỏng.

    Cần thiết cho chạy không người trông: model dịch thỉnh thoảng trả về rỗng,
    Edge-TTS có thể bị giới hạn tần suất.
    """
    attempts = max(1, int(cfg.get('retries', 2)))
    for n in range(1, attempts + 1):
        rc = run_cli(cli_args, log, task_log, env=env, quiet=quiet, stall_timeout=stall_timeout)
        if rc == 0 and succeeded():
            return True
        if rc == STALLED_RC:
            log(f'{head} — treo {int(stall_timeout // 60)} phút không phản hồi, đã dừng')
        if n < attempts:
            log(f'{head} — hỏng lần {n}/{attempts}, thử lại sau 10s...')
            time.sleep(10)
    return False


# ---------------------------------------------------------------------------
# Kiểm tra bản dịch trước khi lồng tiếng — dịch hỏng mà vẫn render thì tốn giờ render + tiền GPU
# ---------------------------------------------------------------------------
# Tốc độ nói của giọng OmniVoice (ký tự/giây, tính cả dấu cách), làm "ngân sách" độ dài câu cho prompt dịch.
# Đo thật (09/2026, video MEXC 98 câu, trung vị): de 18.2, es 18.3, ja 9.1. Các ngôn ngữ khác suy ra theo
# độ dài chữ tương đối, chưa đo. Đặt thấp quá thì AI cắt mất ý (đã gặp: mất chữ "USDT", mất vế so sánh).
# Hán/Nhật/Hàn mỗi ký tự là 1 âm tiết nên số nhỏ hơn nhiều. Ghi đè bằng "speech_cps" trong config.
SPEECH_CPS = {'default': 17, 'de': 18, 'es': 18, 'it': 18, 'pt': 18, 'id': 18, 'ms': 18, 'fil': 18,
              'ja': 9, 'zh': 6, 'ko': 8, 'th': 12, 'ar': 15, 'hi': 16, 'ru': 16, 'uk': 16, 'pl': 16,
              'cs': 16, 'fi': 16, 'el': 16}
# Hệ chữ riêng: câu dịch không có ký tự nào của hệ chữ này mà toàn chữ Latin = chưa dịch / sai ngôn ngữ
SCRIPT_RE = {'ar': r'[؀-ۿ]', 'ja': r'[぀-ヿ一-鿿]', 'ko': r'[가-힯]',
             'ru': r'[Ѐ-ӿ]', 'uk': r'[Ѐ-ӿ]', 'el': r'[Ͱ-Ͽ]',
             'hi': r'[ऀ-ॿ]', 'th': r'[฀-๿]', 'zh': r'[一-鿿]'}
# Từ tiếng Anh gần như không bao giờ xuất hiện trong câu tiếng Đức/Pháp/Tây Ban Nha... đã dịch
# (bỏ "is", "was", "for", "to" vì trùng với tiếng Hà Lan / Bắc Âu)
EN_WORDS = {'the', 'and', 'of', 'you', 'that', 'this', 'with', 'your', 'what', 'have', 'are', 'not',
            'it', 'but', 'they', 'will', 'there', 'from', 'about', 'which', 'would', 'their'}
LLM_JUNK = re.compile(r'</?(TRANSLATE_TEXT|INPUT|think)>|```|^\s*(here is|here\'s|translation\s*:)', re.I)
QA_LABELS = {'empty': 'rỗng', 'junk': 'lẫn chữ thừa của AI', 'untranslated': 'chưa dịch (giống tiếng Anh)',
             'script': 'sai hệ chữ', 'english': 'còn tiếng Anh', 'long': 'dài quá khung thời gian',
             'term': 'mất thuật ngữ phải giữ nguyên'}
# Loại lỗi chỉ để tham khảo (ghi vào báo cáo), không tính là bản dịch hỏng
QA_INFO = ('long', 'term')


def speech_cps(cfg: dict, code: str) -> float:
    table = {**SPEECH_CPS, **(cfg.get('speech_cps') or {})}
    return float(table.get(code) or table.get(code.split('-')[0]) or table['default'])


def check_translation(cfg: dict, source_sub: Path, target_sub: Path, code: str, keep: list = ()) -> tuple:
    """Soát bản dịch: ([(số câu, loại lỗi, nội dung)], nặng?). Loại trong QA_INFO chỉ để tham khảo.

    keep: thuật ngữ phải giữ nguyên (thuat_ngu.py): câu gốc có mà câu dịch mất -> 'term'.

    Bản dịch luôn giữ đúng số câu + thời gian của bản gốc (check_target_sub); AI trả thiếu câu
    thì câu đó thành rỗng -> "rỗng" là dấu hiệu chính của dịch hỏng.
    """
    from videotrans.util.help_srt import get_subtitle_from_srt
    src = get_subtitle_from_srt(str(source_sub))
    tgt = get_subtitle_from_srt(str(target_sub))
    issues = []
    if len(tgt) != len(src):
        issues.append((0, 'empty', f'{len(tgt)}/{len(src)} câu'))
    script = SCRIPT_RE.get(code) or SCRIPT_RE.get(code.split('-')[0])
    latin_target = not script and code.split('-')[0] != 'en'
    cps = speech_cps(cfg, code)

    def words(text):
        return re.findall(r"[^\W\d_]+", text.casefold())

    for i, t in enumerate(tgt):
        text = t['text'].strip()
        s = src[i]['text'].strip() if i < len(src) else ''
        kind = None
        if not text:
            kind = 'empty'
        elif LLM_JUNK.search(text):
            kind = 'junk'
        elif code.split('-')[0] != 'en' and len(words(s)) >= 3 and words(text) == words(s):
            kind = 'untranslated'
        elif script and not re.search(script, text) and len(re.findall(r'[A-Za-z]', text)) >= 6:
            kind = 'script'
        elif latin_target and len(words(text)) >= 5 \
                and sum(w in EN_WORDS for w in words(text)) / len(words(text)) >= 0.35:
            kind = 'english'
        else:
            seconds = (t['end_time'] - t['start_time']) / 1000
            lost = [k for k in keep if re.search(rf'(?<!\w){re.escape(k)}(?!\w)', s)
                    and k.casefold() not in text.casefold()]
            if lost:
                kind = 'term'
                text = f'[{", ".join(lost)}] {text}'
            elif seconds > 0 and len(text) > seconds * cps * 1.6 + 10:
                kind = 'long'
        if kind:
            issues.append((t['line'], kind, text[:120]))
    bad = [x for x in issues if x[1] not in QA_INFO]
    empty = sum(1 for x in bad if x[1] == 'empty')
    severe = len(tgt) != len(src) or empty >= 3 or len(bad) >= max(3, 0.15 * max(1, len(src)))
    return issues, severe


def write_qa_report(path: Path, code: str, issues: list) -> None:
    lines = [f'Soát bản dịch [{code}] — {time.strftime("%Y-%m-%d %H:%M:%S")}', '']
    lines += [f'  câu {line:>4}  {QA_LABELS.get(kind, kind):<28} {text}' for line, kind, text in issues]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def qa_summary(issues: list) -> str:
    counts = {}
    for _, kind, _ in issues:
        counts[kind] = counts.get(kind, 0) + 1
    return ', '.join(f'{n} {QA_LABELS.get(k, k)}' for k, n in counts.items())


# ---------------------------------------------------------------------------
# Pha 1 — dịch phụ đề
# ---------------------------------------------------------------------------
def phase_translate(cfg: dict, langs: list, srt: Path, subs_dir: Path, log: Log,
                    logs_dir: Path) -> dict:
    source_language = cfg.get('source_language', 'en')
    translate_type = int(cfg.get('translate_type', 0))
    subs_dir.mkdir(parents=True, exist_ok=True)

    source_sub = subs_dir / f'{source_language}.srt'
    if not source_sub.exists():
        shutil.copy2(srt, source_sub)
    log(f'  [{source_language}] phụ đề gốc -> {source_sub.name}')

    targets = [l for l in langs if l['code'] != source_language]
    total = len(targets)
    # Mỗi request dịch tối đa llm_timeout (300s) x vài lần thử lại; im lặng lâu hơn thế là treo
    stall_timeout = float(cfg.get('translate_stall_minutes', 20)) * 60 or None

    qa_on = bool(cfg.get('translate_qa', True))
    from videotrans.util.help_srt import get_subtitle_from_srt
    total_cues = len(get_subtitle_from_srt(str(source_sub)))

    # Bảng thuật ngữ: AI đọc cả phụ đề 1 lần, rút tên riêng / mã coin (giữ nguyên) + thuật ngữ (dịch thống
    # nhất); mỗi ngôn ngữ dịch bảng đó rồi chèn vào prompt dịch. Lỗi thì dịch như cũ, không có bảng.
    import thuat_ngu
    glossary_dir = subs_dir / '_thuat_ngu'
    terms = []
    pending = [l for l in targets if not ((subs_dir / f'{l["code"]}.srt').exists()
                                          and (subs_dir / f'{l["code"]}.srt').stat().st_size > 0)]
    if pending and thuat_ngu.available(cfg):
        try:
            terms = thuat_ngu.extract_terms(cfg, source_sub, glossary_dir)
            kept = sum(1 for t in terms if t['keep'])
            log(f'  Bảng thuật ngữ: {len(terms)} mục ({kept} giữ nguyên, {len(terms) - kept} dịch thống nhất) '
                f'— sửa tay được: {glossary_dir / "terms.json"}')
        except Exception as e:  # noqa: BLE001 - không có bảng thì vẫn dịch được
            log(f'  [CẢNH BÁO] Không lập được bảng thuật ngữ ({e}), dịch không kèm bảng.')
    keep = thuat_ngu.keep_terms(glossary_dir)

    def qa(dest: Path, code: str) -> tuple:
        issues, severe = check_translation(cfg, source_sub, dest, code, keep)
        report = logs_dir / f'qa-{code}.txt'
        if issues:
            write_qa_report(report, code, issues)
        else:
            report.unlink(missing_ok=True)
        return issues, severe, report

    def translate_one(i: int, lang: dict, quiet: bool) -> tuple:
        code = lang['code']
        dest = subs_dir / f'{code}.srt'
        head = f'  [{i}/{total}] {code:<6} {lang.get("name", "")}'
        if dest.exists() and dest.stat().st_size > 0:
            # Có thể do người dùng tự sửa -> chỉ cảnh báo, không tự dịch lại
            if qa_on:
                issues, severe, report = qa(dest, code)
                if severe:
                    log(f'{head} — đã có, nhưng [CẢNH BÁO] bản dịch hỏng nặng ({qa_summary(issues)}); '
                        f'xoá {dest.name} rồi chạy lại để dịch lại. Chi tiết: {report}')
                    return code, 'skipped'
            log(f'{head} — đã có, bỏ qua')
            return code, 'skipped'

        # translate_srt.py ghi ra {output-dir}/{tên file nguồn}.{mã ngôn ngữ}.srt
        # Mỗi ngôn ngữ một tên file riêng nên chạy song song không giẫm lên nhau.
        produced = subs_dir / f'{source_sub.stem}.{code}.srt'
        cli_args = [
            '--task', 'sts',
            '--name', str(source_sub),
            '--source_language_code', source_language,
            '--target_language_code', code,
            '--translate_type', str(translate_type),
            '--output-dir', str(subs_dir),
        ]
        # Ngân sách độ dài câu theo thời gian (prompt dịch): câu dịch vừa khung thì giọng đọc
        # không phải tua nhanh / đọc lại
        env = {'PYVIDEOTRANS_DUB_CPS': f'{speech_cps(cfg, code):g}'} \
            if cfg.get('translate_timing_budget', False) else {}
        if terms:
            try:
                env[thuat_ngu.GLOSSARY_ENV] = str(thuat_ngu.glossary_for(cfg, terms, code, glossary_dir))
            except Exception as e:  # noqa: BLE001
                log(f'{head} — [CẢNH BÁO] không dịch được bảng thuật ngữ ({e}), dịch không kèm bảng')
        best = None  # (điểm, file, lỗi, nặng?)
        tries = 2 if qa_on else 1
        for n in range(1, tries + 1):
            log(f'{head} — đang dịch...' if n == 1 else f'{head} — dịch lại lần {n}...')
            produced.unlink(missing_ok=True)
            try:
                done = attempt(cfg, log, head, logs_dir / f'translate-{code}.log', cli_args,
                               lambda: produced.exists() and produced.stat().st_size > 0,
                               env=env, quiet=quiet, stall_timeout=stall_timeout)
            except Exception as e:  # noqa: BLE001 - một ngôn ngữ hỏng không được làm sập cả loạt
                log(f'{head} — LỖI: {e}')
                done = False
            if not done:
                break
            candidate = subs_dir / f'_{code}.lan{n}.srt'
            produced.replace(candidate)
            if not qa_on:
                best = (0, candidate, [], False)
                break
            issues, severe = check_translation(cfg, source_sub, candidate, code, keep)
            bad = [x for x in issues if x[1] not in QA_INFO]
            score = (severe, len(bad))
            if best is None or score < best[0]:
                best = (score, candidate, issues, severe)
            # Lỗi lẻ tẻ 1-2 câu thì giữ (xem logs/qa-<mã>.txt); nhiều hơn thì dịch lại 1 lần
            if not severe and len(bad) < max(2, 0.05 * total_cues):
                break
            if n < tries:
                log(f'{head} — bản dịch có lỗi ({qa_summary(bad)}), dịch lại...')

        if best is None:
            log(f'{head} — LỖI (chi tiết: {logs_dir / f"translate-{code}.log"})')
            return code, 'failed'
        for leftover in subs_dir.glob(f'_{code}.lan*.srt'):
            if leftover != best[1]:
                leftover.unlink(missing_ok=True)
        _, candidate, issues, severe = best
        if severe:
            bad_dir = subs_dir / '_loi'
            bad_dir.mkdir(exist_ok=True)
            candidate.replace(bad_dir / f'{code}.srt')
            issues, _, report = qa(bad_dir / f'{code}.srt', code)
            log(f'{head} — LỖI: bản dịch hỏng nặng sau 2 lần dịch ({qa_summary(issues)}), '
                f'bỏ qua lồng tiếng ngôn ngữ này. Chi tiết: {report}')
            return code, 'failed'
        candidate.replace(dest)
        issues, _, report = qa(dest, code) if qa_on else ([], False, None)
        log(f'{head} — xong' + (f' ({qa_summary(issues)} — xem {report.name})' if issues else ''))
        return code, 'ok'

    # Dịch chỉ là chờ API, không tốn CPU/GPU, nên chạy song song nhiều ngôn ngữ
    # rút ngắn pha này gần như tuyến tính. Hạ xuống nếu nhà cung cấp chặn tần suất.
    parallel = max(1, int(cfg.get('translate_parallel', 4)))
    results = {}

    if parallel == 1 or total <= 1:
        for i, lang in enumerate(targets, start=1):
            code, status = translate_one(i, lang, quiet=False)
            results[code] = status
        return results

    log(f'  Dịch song song {parallel} ngôn ngữ cùng lúc '
        f'(sửa "translate_parallel" trong dub_all.config.json để đổi).')
    log('  Output chi tiết của từng ngôn ngữ nằm trong logs/translate-<mã>.log')
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(translate_one, i, lang, True): lang['code']
                   for i, lang in enumerate(targets, start=1)}
        for fut in as_completed(futures):
            code, status = fut.result()
            results[code] = status
    return results


# ---------------------------------------------------------------------------
# Pha 2 — lồng tiếng + render
# ---------------------------------------------------------------------------
SEPARATE_FILES = ('vocal.wav', 'instrument.wav')


def seed_separated_audio(sep_dir: Path, lang_out: Path) -> None:
    """Đặt sẵn nhạc nền đã tách vào thư mục ngôn ngữ để prepare() nạp lại, khỏi tách lại."""
    lang_out.mkdir(parents=True, exist_ok=True)
    for name in SEPARATE_FILES:
        master, dest = sep_dir / name, lang_out / name
        if not master.exists() or dest.exists():
            continue
        try:
            os.link(master, dest)
        except OSError:
            shutil.copy2(master, dest)


def harvest_separated_audio(sep_dir: Path, lang_out: Path) -> None:
    """Giữ lại 1 bản nhạc nền dùng chung, xoá bản trùng trong thư mục từng ngôn ngữ."""
    sep_dir.mkdir(parents=True, exist_ok=True)
    for name in SEPARATE_FILES:
        master, produced = sep_dir / name, lang_out / name
        if not produced.exists():
            continue
        if master.exists():
            produced.unlink(missing_ok=True)
        else:
            shutil.move(str(produced), str(master))


def auto_render_parallel(encoder: str = 'libx264') -> tuple:
    """Số video render cùng lúc hợp với máy: (số, lý do). Render nặng CPU/RAM, máy yếu làm nhiều sẽ lỗi/treo.

    Đo thực tế (i5-14600K): 1 video libx264 đã chiếm gần hết CPU, 3 video cùng lúc chỉ nhanh hơn ~16%;
    NVENC 3 video cùng lúc còn chậm hơn chạy CPU. Chạy 2 cùng lúc chủ yếu để phần không phải mã hoá
    (ghép tiếng, co giãn giọng, khởi động) của video này lấp vào lúc video kia đang mã hoá.
    """
    try:
        import psutil
        cores = psutil.cpu_count(logical=False) or os.cpu_count() or 2
        ram = psutil.virtual_memory().total / 2 ** 30
    except Exception:  # noqa: BLE001
        cores, ram = os.cpu_count() or 2, 8.0
    info = f'{cores} nhân CPU, {ram:.0f} GB RAM, mã hoá {encoder}'
    if ram < 12 or cores < 4:
        return 1, info
    if encoder != 'libx264':  # mã hoá trên card đồ hoạ: CPU còn rảnh để giải mã + vẽ phụ đề video thứ 2
        return 2, info
    return (2 if cores >= 6 and ram >= 16 else 1), info


def render_parallel(cfg: dict, log=None) -> int:
    value = str(cfg.get('dub_parallel', 'auto')).strip().lower()
    if value.isdigit() and int(value) >= 1:
        return int(value)
    n, info = auto_render_parallel(video_encoder(cfg)['name'])
    if log:
        log(f'  Máy này: {info} -> render {n} video cùng lúc (dub_parallel = auto)')
    return n


# ---------------------------------------------------------------------------
# Chọn bộ mã hoá video. Phụ đề nhúng cứng -> mỗi video bắt buộc mã hoá lại toàn bộ hình,
# đây là khâu tốn thời gian nhất cả quy trình.
# ---------------------------------------------------------------------------
HW_ENCODERS = ('h264_nvenc', 'h264_qsv', 'h264_amf')
ENCODER_CACHE = ROOT_DIR / 'videotrans' / 'encoder_choice.json'
# Mã hoá bằng card cho file to hơn / kém nét hơn libx264 ở cùng dung lượng -> chỉ chọn khi nhanh hơn rõ rệt
HW_MIN_SPEEDUP = 1.3


def encoder_args(name: str, preset: str, crf: int) -> list:
    """Tham số ffmpeg cho từng bộ mã hoá, chất lượng quy về cùng thang crf của libx264."""
    q = str(crf + 3)  # thang chất lượng của card đồ hoạ lệch với crf libx264 khoảng vài bậc
    if name == 'h264_nvenc':
        return ['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc', 'vbr', '-cq', q, '-b:v', '0', '-pix_fmt', 'yuv420p']
    if name == 'h264_qsv':
        return ['-c:v', 'h264_qsv', '-preset', 'veryfast', '-global_quality', q]
    if name == 'h264_amf':
        return ['-c:v', 'h264_amf', '-quality', 'speed', '-rc', 'cqp', '-qp_i', q, '-qp_p', q, '-qp_b', q]
    return ['-c:v', 'libx264', '-preset', preset, '-crf', str(crf), '-pix_fmt', 'yuv420p']


def video_encoder(cfg: dict) -> dict:
    """Bộ mã hoá đã chọn (choose_video_encoder), chưa chọn thì libx264 theo config."""
    if cfg.get('_video_encoder'):
        return cfg['_video_encoder']
    preset, crf = str(cfg.get('video_preset', 'veryfast')), int(cfg.get('video_crf', 21))
    args = encoder_args('libx264', preset, crf)
    return {'name': 'libx264', 'args': args, 'fallback': args}


def _probe_video(video: Path) -> tuple:
    """(rộng, cao, số giây) của luồng hình đầu tiên."""
    rs = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                         '-show_entries', 'stream=width,height:format=duration',
                         '-of', 'default=noprint_wrappers=1', str(video)],
                        capture_output=True, text=True, encoding='utf-8', errors='replace')
    info = dict(line.split('=', 1) for line in rs.stdout.splitlines() if '=' in line)
    try:
        return int(info.get('width', 0)), int(info.get('height', 0)), float(info.get('duration', 0))
    except ValueError:
        return 0, 0, 0.0


def _time_ffmpeg(cmd: list, cwd: Path, timeout: int = 180):
    started = time.perf_counter()
    try:
        rs = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return time.perf_counter() - started if rs.returncode == 0 else None


def choose_video_encoder(cfg: dict, video: Path, work: Path, log: Log) -> dict:
    """Chạy thử vài giây trên chính video này với từng bộ mã hoá máy có, chọn cái nhanh nhất.

    Kết quả nhớ trong videotrans/encoder_choice.json theo máy + độ phân giải, lần sau khỏi đo.
    Không tin danh sách `ffmpeg -encoders`: máy có thể liệt kê h264_qsv mà chạy thật thì lỗi.
    """
    preset, crf = str(cfg.get('video_preset', 'veryfast')), int(cfg.get('video_crf', 21))
    fallback = encoder_args('libx264', preset, crf)
    wanted = str(cfg.get('video_encoder', 'auto')).strip().lower()

    def result(name: str) -> dict:
        return {'name': name, 'args': encoder_args(name, preset, crf), 'fallback': fallback}

    if wanted != 'auto':
        if wanted not in ('libx264',) + HW_ENCODERS:
            log(f'  [CẢNH BÁO] video_encoder "{wanted}" không hỗ trợ, dùng libx264')
            wanted = 'libx264'
        log(f'  Mã hoá video: {wanted} (đặt cố định trong dub_all.config.json)')
        return result(wanted)

    width, height, duration = _probe_video(video)
    version = subprocess.run(['ffmpeg', '-hide_banner', '-version'], capture_output=True, text=True,
                             encoding='utf-8', errors='replace').stdout.split('\n', 1)[0]
    listed = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True,
                            encoding='utf-8', errors='replace').stdout
    candidates = ['libx264'] + [e for e in HW_ENCODERS if f' {e} ' in listed]
    key = f'{platform.node()}|{width}x{height}|{preset}|{crf}|{version}|{",".join(candidates)}'
    try:
        cache = json.loads(ENCODER_CACHE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(key)
    if isinstance(hit, dict) and hit.get('name') in candidates:
        log(f'  Mã hoá video: {hit["name"]} (đã đo trên máy này: {hit.get("summary", "")})')
        return result(hit['name'])

    work.mkdir(parents=True, exist_ok=True)
    (work / 'bench.srt').write_text('1\n00:00:00,000 --> 00:10:00,000\nSubtitle benchmark line\n\n',
                                    encoding='utf-8')
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', 'bench.srt', 'bench.ass'],
                   cwd=str(work), capture_output=True)
    seconds = max(1.0, min(6.0, duration - 0.5)) if duration else 6.0
    start = max(0.0, min(duration * 0.4, duration - seconds - 0.5)) if duration else 0.0
    head = ['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'error', '-ss', f'{start:.2f}',
            '-t', f'{seconds:.2f}', '-i', str(video), '-an', '-vf', "subtitles=filename='bench.ass'"]
    log(f'  Đo tốc độ mã hoá trên máy này ({", ".join(candidates)}), chỉ làm lần đầu...')
    # Lượt khởi động: lần đầu libass dựng cache font có thể mất vài giây, không tính vào bộ mã hoá nào
    _time_ffmpeg(head + ['-f', 'null', '-'], work)
    times = {name: _time_ffmpeg(head + encoder_args(name, preset, crf) + ['-f', 'null', '-'], work)
             for name in candidates}
    shutil.rmtree(work, ignore_errors=True)

    summary = ', '.join(f'{n} {t:.1f}s' if t else f'{n} lỗi' for n, t in times.items())
    base = times.get('libx264')
    hw = [(t, n) for n, t in times.items() if n != 'libx264' and t]
    name = 'libx264'
    if hw:
        best_t, best = min(hw)
        if not base or best_t * HW_MIN_SPEEDUP <= base:
            name = best
    log(f'  Mã hoá video: {name} (đo {seconds:.0f}s video: {summary})')
    if base or hw:  # đo hỏng hết thì không nhớ, lần sau đo lại
        cache[key] = {'name': name, 'summary': summary, 'date': time.strftime('%Y-%m-%d')}
        try:
            ENCODER_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass
    return result(name)


# ---------------------------------------------------------------------------
# Tách nhạc nền chạy nền, song song với bước dịch (dịch chỉ là chờ API, CPU đang rảnh)
# ---------------------------------------------------------------------------
def run_separate_worker(video: str, sep_dir: str, model: str) -> int:
    """Tiến trình con (dub_all.py --separate-worker): tách video ra sep_dir/vocal.wav + instrument.wav.

    Làm y như bước tách trong _stage_prepare để 25 ngôn ngữ dùng lại được qua seed_separated_audio.
    Ghi ra file tạm rồi mới đổi tên: phase_dub coi instrument.wav có mặt là đã tách xong.
    """
    from videotrans.configure import config as vt_config
    vt_config.init_run()
    from videotrans.configure.config import settings
    from videotrans.configure.contants import UVR_URL_MS, UVR_URL_HF
    from videotrans.process._audio_separate import vocal_bgm
    from videotrans.util.help_down import down_file_from_hf
    from videotrans.util.help_misc import is_connect_hf

    out = Path(sep_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw = out / '_raw_44100.wav'
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-nostdin', '-loglevel', 'error', '-i', video,
                    '-vn', '-ac', '2', '-ar', '44100', '-c:a', 'pcm_s16le', str(raw)], check=True)
    model = model or settings.get('uvr_models') or 'UVR-MDX-NET-Inst_HQ_4'
    prefix = UVR_URL_HF if is_connect_hf() else UVR_URL_MS
    names = ['vocals.fp16.onnx', 'accompaniment.fp16.onnx'] if model.startswith('spleeter') else [f'{model}.onnx']
    down_file_from_hf(str(ROOT_DIR / 'models' / 'onnx'), [prefix.replace('{}', n) for n in names])
    vocal_tmp, instr_tmp = out / '_vocal.part.wav', out / '_instrument.part.wav'
    print(f'Tách bằng {model}: {video}', flush=True)
    started = time.time()
    ok, err = vocal_bgm(input_file=str(raw), vocal_file=str(vocal_tmp), instr_file=str(instr_tmp),
                        uvr_models=model)
    raw.unlink(missing_ok=True)
    if not ok or not vocal_tmp.exists() or not instr_tmp.exists():
        print(f'Tách thất bại: {err}', flush=True)
        return 1
    os.replace(vocal_tmp, out / 'vocal.wav')
    os.replace(instr_tmp, out / 'instrument.wav')
    print(f'Xong sau {time.time() - started:.1f}s', flush=True)
    return 0


def _has_audio(video: Path) -> bool:
    rs = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                         '-of', 'csv=p=0', str(video)], capture_output=True, text=True)
    return bool(rs.stdout.strip())


def start_separation(cfg: dict, video: Path, sep_dir: Path, logs_dir: Path, log: Log):
    """Bắt đầu tách nhạc nền ở tiến trình riêng, trả về thread để phase_dub chờ (None nếu không cần)."""
    if not cfg.get('is_separate') or not _has_audio(video):
        return None
    if (sep_dir / 'vocal.wav').exists() and (sep_dir / 'instrument.wav').exists():
        return None
    task_log = logs_dir / 'separate.log'

    def work():
        started = time.time()
        cmd = [sys.executable, str(Path(__file__).resolve()), '--separate-worker',
               str(video), str(sep_dir), str(cfg.get('uvr_model') or '')]
        with task_log.open('a', encoding='utf-8') as fh:
            fh.write(f'\n$ {" ".join(cmd)}\n')
            fh.flush()
            rc = subprocess.run(cmd, cwd=str(ROOT_DIR), stdout=fh, stderr=subprocess.STDOUT,
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}).returncode
        if rc == 0 and (sep_dir / 'instrument.wav').exists():
            log(f'  Tách nhạc nền + SFX xong sau {fmt_duration(time.time() - started)}')
        else:
            log(f'  [CẢNH BÁO] Tách nhạc nền chạy trước bị lỗi (xem {task_log}) — '
                f'sẽ tách lại ở ngôn ngữ đầu tiên')

    log('  Tách nhạc nền + SFX chạy song song, trong lúc dịch / tạo giọng')
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread


class TtsPrefetch:
    """Tạo giọng chạy nền; phase_dub chờ riêng từng ngôn ngữ (ngôn ngữ nào xong giọng là render ngay)."""

    def __init__(self):
        self.ready = {}      # mã ngôn ngữ -> threading.Event
        self.thread = None

    def wait(self, code: str, log: Log, head: str) -> None:
        event = self.ready.get(code)
        if event and not event.is_set():
            log(f'{head} — chờ tạo giọng trên GPU Modal...')
            event.wait()

    def join(self) -> None:
        if self.thread:
            self.thread.join()


def prefetch_parallel(cfg: dict) -> int:
    """Số lượt tạo giọng cùng lúc trên GPU Modal. "auto" = theo tốc độ render của máy này: GPU chỉ cần
    tạo giọng nhanh hơn máy render là đủ, thêm GPU chỉ tốn thêm tiền khởi động. Đo thực tế (video
    6 phút, 98 câu/ngôn ngữ): 4 GPU ~65 giây/ngôn ngữ; máy mạnh render 2 video cùng lúc ~30 giây/ngôn
    ngữ -> cần 8, máy văn phòng render 1 video ~vài phút/ngôn ngữ -> 4 là dư."""
    value = str(cfg.get('tts_prefetch_parallel', 'auto')).strip().lower()
    if value.isdigit() and int(value) >= 1:
        return int(value)
    renders = render_parallel(cfg)
    return min(8, 4 * max(1, renders))


def subtitle_windows(items: list, video_seconds: float) -> dict:
    """{câu: số giây giọng đọc được phép chiếm}, tính giống _rate.SpeedRate: từ đầu câu này tới
    đầu câu sau (khoảng lặng giữa 2 câu cũng dùng được); câu cuối tới hết video. Câu lặp lại thì
    lấy khung ngắn nhất."""
    windows = {}
    for i, it in enumerate(items):
        end = items[i + 1]['start_time'] if i + 1 < len(items) else max(it['end_time'], video_seconds * 1000)
        seconds = (end - it['start_time']) / 1000
        windows[it['text']] = min(seconds, windows.get(it['text'], seconds))
    return windows


def write_tts_qc_report(path: Path, code: str, rows: list, median: float = None) -> None:
    """logs/qc-<mã>.txt: câu mà Whisper nghe lại vẫn lệch sau các lần đọc lại -> người dùng nghe kiểm."""
    from videotrans.tts._omnivoice_modal import QC_HEALTHY_MEDIAN
    weak = median is not None and median < QC_HEALTHY_MEDIAN
    if not rows:
        path.unlink(missing_ok=True)
        return
    lines = [f'Nghe lại giọng đọc [{code}] — {time.strftime("%Y-%m-%d %H:%M:%S")}', '']
    if weak:
        lines += [f'Whisper nghe CẢ ngôn ngữ này ra lệch (điểm trung vị {median:.2f}, ngôn ngữ bình thường '
                  f'0.92-1.00).', 'Thường do giọng mẫu tiếng Anh làm đọc lơ lớ, hoặc Whisper nghe kém ngôn ngữ '
                  'này -> không tự đọc lại.', 'Nghe thử vài câu: nếu lơ lớ, thử "omnivoice_voice": "native" '
                  'cho ngôn ngữ này trong dub_all.config.json.', 'Các câu điểm thấp nhất:', '']
        rows = sorted(rows, key=lambda r: r[2])[:10]
    else:
        lines += ['Câu dưới đây Whisper nghe ra khác câu yêu cầu (đọc sót / lặp / sai từ) dù đã đọc lại. '
                  'Điểm 0-1, càng thấp càng lệch.', 'Nghe kiểm trong video; sửa chữ trong phụ đề hoặc thêm '
                  'cách đọc vào phat_am.json rồi chạy lại.', '']
    for text, heard, score in sorted(rows, key=lambda r: r[2]):
        lines += [f'  [{score:.2f}] cần đọc : {text}', f'         nghe được: {heard}', '']
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def omnivoice_ref_warning(cfg: dict) -> str:
    """OmniVoice mà không có giọng mẫu cố định thì lặng lẽ chuyển sang nhái từng câu từ video: không tạo
    giọng trước được (mỗi ngôn ngữ chờ GPU rồi mới render, 1 GPU khởi động lại mỗi ngôn ngữ), không đọc
    lại câu dài cho vừa khung, không có Whisper nghe lại. Đo log máy nhân viên 10/2026: ~9.5 phút/ngôn
    ngữ thay vì ~5. Trả về lời cảnh báo, hoặc '' nếu ổn."""
    if int(cfg.get('tts_type', EDGE_TTS)) != OMNIVOICE_TTS:
        return ''
    from videotrans.tts._omnivoice_modal import fixed_ref, remote_configured
    if not remote_configured():
        return ''
    try:
        if fixed_ref():
            return ''
        why = 'Chưa có giọng mẫu cố định'
    except FileNotFoundError as e:
        why = f'Không thấy file giọng mẫu ({e})'
    return (f'{why} -> OmniVoice sẽ nhái từng câu từ video gốc: chậm gần gấp đôi (không tạo giọng trước '
            f'song song), không đọc lại câu dài cho vừa khung, không có Whisper nghe lại, giọng không phải '
            f'giọng mẫu. Cài giọng mẫu: DOI_TTS.bat mục 3 (kéo thả file giọng mẫu vào).')


def start_tts_prefetch(cfg: dict, langs: list, video: Path, subs_dir: Path, final_dir: Path,
                       store: Path, log: Log, logs_dir: Path = None) -> TtsPrefetch:
    """OmniVoice + giọng mẫu cố định: tạo sẵn giọng mọi ngôn ngữ trên GPU Modal, chạy nền.

    Ngôn ngữ nào tạo xong giọng thì render ngay trên máy này, song song với GPU tạo giọng ngôn ngữ
    tiếp theo. Nhái từng câu từ video thì không tạo sẵn được (giọng mẫu cắt từ video trong lúc
    lồng tiếng) -> đọc trong lúc lồng tiếng như cũ.
    """
    job = TtsPrefetch()
    if int(cfg.get('tts_type', EDGE_TTS)) != OMNIVOICE_TTS:
        return job
    from videotrans.tts._omnivoice_modal import fixed_ref, prefetch, remote_configured
    from videotrans.util.help_srt import get_subtitle_from_srt
    if not remote_configured() or not fixed_ref():
        return job
    video_seconds = _probe_video(video)[2]
    jobs, slots = {}, {}
    for lang in langs:
        sub = subs_dir / f'{lang["code"]}.srt'
        if find_final_video(final_dir, lang, video.stem) or not sub.exists():
            continue
        # Giống hệt cách _stage_dubbing lấy câu để đọc -> kho khớp đúng từng câu lúc render
        items = [it for it in get_subtitle_from_srt(str(sub))
                 if it['end_time'] >= it['start_time'] and it['text'].strip()]
        jobs[lang['code']] = [it['text'] for it in items]
        slots[lang['code']] = subtitle_windows(items, video_seconds)
    if not jobs:
        return job
    job.ready = {code: threading.Event() for code in jobs}
    parallel = prefetch_parallel(cfg)
    native ={l['code'] for l in langs if str(l.get('omnivoice_voice', '')).lower() == 'native'}

    def run():
        started = time.time()
        try:
            res = prefetch(store, jobs, parallel=parallel, log=log,
                           native=native & set(jobs), slots=slots,
                           fit_ratio=float(cfg.get('tts_fit_ratio', 1.2) or 0),
                           on_ready=lambda code: job.ready[code].set(),
                           qc_min=float(cfg.get('tts_qc_min', 0.75) or 0),
                           qc_retries=int(cfg.get('tts_qc_retries', 2)),
                           on_qc=(lambda code, rows, med: write_tts_qc_report(logs_dir / f'qc-{code}.txt', code, rows, med))
                           if logs_dir else None)
            done = sum(v[0] for v in res.values())
            refit = sum(v[2] for v in res.values())
            log(f'  Tạo sẵn giọng xong sau {fmt_duration(time.time() - started)}: {done} câu, '
                f'{len(res)} ngôn ngữ' + (f', {refit} câu đọc lại cho vừa khung' if refit else ''))
        except Exception as e:  # noqa: BLE001 - tạo sẵn lỗi thì lúc render tự đọc như cũ
            log(f'  [CẢNH BÁO] Tạo sẵn giọng lỗi ({e}), sẽ đọc trong lúc lồng tiếng.')
        finally:
            for event in job.ready.values():
                event.set()

    job.thread = threading.Thread(target=run, daemon=True)
    job.thread.start()
    return job


def phase_dub(cfg: dict, langs: list, video: Path, subs_dir: Path, out_dir: Path,
              final_dir: Path, style_dir: Path, log: Log, logs_dir: Path,
              tts: TtsPrefetch = None) -> dict:
    source_language = cfg.get('source_language', 'en')
    source_sub = subs_dir / f'{source_language}.srt'
    sleep_between = float(cfg.get('sleep_between', 5))
    is_separate = bool(cfg.get('is_separate'))
    sep_dir = out_dir.parent / '_separate'
    results = {}

    if is_separate and not (sep_dir / 'instrument.wav').exists():
        log('  Giữ nhạc nền + SFX: sẽ tách nhạc khỏi giọng nói ở ngôn ngữ đầu tiên')
        log('  (chỉ tách 1 lần cho cả loạt, có thể mất vài phút với video dài)')
    enc = video_encoder(cfg)
    video_seconds = _probe_video(video)[2]

    def dub_one(i: int, lang: dict, quiet: bool) -> tuple:
        code = lang['code']
        head = f'  [{i}/{len(langs)}] {code:<6} {lang.get("name", "")}'
        lang_out = out_dir / code
        if find_final_video(final_dir, lang, video.stem):
            log(f'{head} — đã hoàn thành, bỏ qua')
            return code, 'skipped'
        # Còn sót từ lần chạy bị ngắt giữa chừng: chỉ cần hoàn tất nốt
        leftover = find_output_video(lang_out, video.stem)
        if leftover:
            log(f'{head} — đã render sẵn, hoàn tất nốt')
            if is_separate:
                harvest_separated_audio(sep_dir, lang_out)
            finalize(cfg, log, head, leftover, lang_out, final_dir, lang, video.stem)
            return code, 'skipped'

        target_sub = subs_dir / f'{code}.srt'
        if code != source_language and not (target_sub.exists() and target_sub.stat().st_size > 0):
            log(f'{head} — LỖI: thiếu phụ đề {target_sub.name}, bỏ qua')
            return code, 'failed'

        if tts:
            tts.wait(code, log, head)

        style_file = style_dir / f'{code}.json'
        style_file.write_text(json.dumps(style_for(cfg, code), ensure_ascii=False, indent=2),
                              encoding='utf-8')
        if is_separate:
            seed_separated_audio(sep_dir, lang_out)

        cli_args = [
            '--task', 'vtv',
            '--name', str(video),
            '--source_language_code', source_language,
            '--target_language_code', code,
            '--source_srt', str(source_sub),
            '--tts_type', str(cfg.get('tts_type', EDGE_TTS)),
            # Edge-TTS: giọng riêng từng ngôn ngữ. TTS chạy trên máy (OmniVoice...): "clone" =
            # nhái giọng người nói, mỗi câu lấy đúng đoạn gốc trong video làm giọng mẫu
            '--voice_role', lang['voice'] if int(cfg.get('tts_type', EDGE_TTS)) == EDGE_TTS
            else cfg.get('local_tts_voice', 'clone'),
            '--voice_rate', cfg.get('voice_rate', '+0%'),
            '--volume', cfg.get('volume', '+0%'),
            '--pitch', cfg.get('pitch', '+0Hz'),
            '--subtitle_type', str(cfg.get('subtitle_type', 1)),
            '--output-dir', str(lang_out),
            '--no-clear-cache',
        ]
        if code != source_language:
            cli_args += ['--target_srt', str(target_sub)]
        if cfg.get('voice_autorate'):
            cli_args.append('--voice_autorate')
        if cfg.get('video_autorate'):
            cli_args.append('--video_autorate')
        if cfg.get('cuda'):
            cli_args.append('--cuda')
        if is_separate:
            cli_args += ['--is_separate',
                         '--backaudio_volume', str(cfg.get('backaudio_volume', 0.8))]

        env = {'PYVIDEOTRANS_ASS_JSON': str(style_file),
               'PYVIDEOTRANS_SUB_MAXLEN': str(maxlen_for(cfg, code)),
               'PYVIDEOTRANS_EDGETTS_CONCURRENCY': str(max(1, int(cfg.get('tts_concurrency', 3)))),
               # kho giọng OmniVoice tạo sẵn (phase_tts_prefetch) — trúng thì không gọi Modal nữa
               'PYVIDEOTRANS_OMNIVOICE_STORE': str(out_dir.parent / '_tts'),
               # "omnivoice_voice": "native" trong languages: giọng bản xứ thay cho giọng mẫu tiếng Anh
               'PYVIDEOTRANS_OMNIVOICE_VOICE': str(lang.get('omnivoice_voice', '')),
               # bộ mã hoá đã đo chọn trên máy này (choose_video_encoder) + dự phòng libx264
               'PYVIDEOTRANS_VIDEO_ENC': json.dumps(enc['args']),
               'PYVIDEOTRANS_VIDEO_ENC_FALLBACK': json.dumps(enc['fallback']),
               # không xuất thêm file .m4a tiếng gốc / tiếng lồng vào thư mục ngôn ngữ (không dùng tới)
               'PYVIDEOTRANS_LEAN_OUTPUT': '1'}
        if int(cfg.get('subtitle_type', 1)) in (1, 3) and not cfg.get('video_autorate'):
            # đằng nào cũng mã hoá lại để nhúng phụ đề: đọc thẳng hình từ video gốc,
            # khỏi tạo novoice.mp4 (bản sao cả video) cho từng ngôn ngữ
            env['PYVIDEOTRANS_NOVOICE_DIRECT'] = '1'
        if cfg.get('normalize_audio'):
            # chuẩn hoá âm lượng ngay trên tiếng trước khi ghép hình, khỏi ghi lại cả video lần nữa
            env['PYVIDEOTRANS_LOUDNORM'] = (f'{cfg.get("loudnorm_i", -14)}:{cfg.get("loudnorm_tp", -1.5)}'
                                            f':{cfg.get("loudnorm_lra", 11)}')
        if is_separate and cfg.get('uvr_model'):
            env['PYVIDEOTRANS_UVR_MODEL'] = str(cfg['uvr_model'])

        voice_label = lang['voice'] if int(cfg.get('tts_type', EDGE_TTS)) == EDGE_TTS \
            else TTS_LABELS.get(int(cfg.get('tts_type')), 'TTS').split(' (')[0] + ' (GPU Modal)'
        log(f'{head} — lồng tiếng {voice_label} ...')
        started = time.time()
        # 1 ngôn ngữ bình thường ~5-6 phút; im lặng quá dub_stall_minutes là treo -> giết, chạy lại.
        # ffmpeg render cuối không in gì: video dài thì cho im lặng tới bằng độ dài video (máy 4 nhân
        # libx264 render ~0.3 lần thời lượng). Lần còn phải tự tách nhạc nền trong cli.py thì không canh
        # (UVR trên CPU im lặng cả chục phút)
        stall = float(cfg.get('dub_stall_minutes', 30)) * 60 or None
        if stall:
            stall = max(stall, video_seconds)
        if is_separate and not (sep_dir / 'instrument.wav').exists():
            stall = None
        done = attempt(cfg, log, head, logs_dir / f'dub-{code}.log', cli_args,
                       lambda: find_output_video(lang_out, video.stem) is not None, env=env, quiet=quiet,
                       stall_timeout=stall)

        if is_separate:
            harvest_separated_audio(sep_dir, lang_out)
            if not (sep_dir / 'instrument.wav').exists():
                log(f'{head} — [CẢNH BÁO] tách nhạc nền thất bại, video này MẤT nhạc/SFX. '
                    f'Xem {logs_dir / f"dub-{code}.log"}')

        produced = find_output_video(lang_out, video.stem)
        if done and produced:
            finalize(cfg, log, head, produced, lang_out, final_dir, lang, video.stem)
            log(f'{head} — xong sau {fmt_duration(time.time() - started)}')
            return code, 'ok'
        log(f'{head} — LỖI (chi tiết: {logs_dir / f"dub-{code}.log"})')
        return code, 'failed'

    # OmniVoice trên GPU Modal: giọng đã tạo sẵn (hoặc đọc trên máy chủ), phần còn lại là render
    # trên máy này -> số ngôn ngữ làm cùng lúc theo sức máy (dub_parallel, "auto" = tự chọn).
    # Edge-TTS giữ lần lượt vì Microsoft chặn khi gọi dồn dập.
    parallel = 1 if int(cfg.get('tts_type', EDGE_TTS)) == EDGE_TTS else render_parallel(cfg, log)
    todo = list(enumerate(langs, start=1))
    if parallel == 1 or len(todo) <= 1:
        for n, (i, lang) in enumerate(todo, start=1):
            code, status = dub_one(i, lang, quiet=False)
            results[code] = status
            if status == 'ok' and n < len(todo) and sleep_between > 0:
                time.sleep(sleep_between)
    else:
        # Tách nhạc nền chỉ làm 1 lần ở ngôn ngữ đầu: chạy riêng nó trước rồi mới chạy song song
        if is_separate and not (sep_dir / 'instrument.wav').exists():
            first = next((k for k, (_, l) in enumerate(todo)
                          if not find_final_video(final_dir, l, video.stem)), None)
            if first is not None:
                i, lang = todo.pop(first)
                code, status = dub_one(i, lang, quiet=False)
                results[code] = status
        log(f'  Lồng tiếng + render {parallel} ngôn ngữ cùng lúc '
            f'(sửa "dub_parallel" trong dub_all.config.json để đổi).')
        log('  Output chi tiết của từng ngôn ngữ nằm trong logs/dub-<mã>.log')
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [pool.submit(dub_one, i, lang, True) for i, lang in todo]
            for fut in as_completed(futures):
                try:
                    code, status = fut.result()
                except Exception as e:  # noqa: BLE001 - 1 ngôn ngữ hỏng không làm sập cả loạt
                    log(f'  LỖI không mong đợi: {e}')
                    continue
                results[code] = status

    if cfg.get('cleanup_out', True) and out_dir.is_dir() and not any(out_dir.iterdir()):
        out_dir.rmdir()
    return results


# ---------------------------------------------------------------------------
# Video gốc — chỉ nhúng phụ đề gốc, không lồng tiếng
# ---------------------------------------------------------------------------
def original_lang(cfg: dict) -> dict:
    """Mục 'ngôn ngữ' ảo đại diện cho video gốc, dùng chung cách đặt tên file với 25 bản kia."""
    source_language = cfg.get('source_language', 'en')
    opts = cfg.get('original_video') or {}
    return {'code': source_language, 'name': opts.get('name') or 'Gốc', 'voice': '(giọng gốc)'}


def original_enabled(cfg: dict) -> bool:
    return bool((cfg.get('original_video') or {}).get('enabled', True))


def phase_original(cfg: dict, video: Path, subs_dir: Path, workdir: Path, final_dir: Path,
                   style_dir: Path, log: Log, logs_dir: Path) -> str:
    """Nhúng phụ đề cứng ngôn ngữ gốc vào video gốc. Giữ nguyên hình và tiếng, không TTS."""
    lang = original_lang(cfg)
    code = lang['code']
    head = f'  [gốc] {code:<6} {lang["name"]}'
    if find_final_video(final_dir, lang, video.stem):
        log(f'{head} — đã hoàn thành, bỏ qua')
        return 'skipped'

    source_sub = subs_dir / f'{code}.srt'
    if not (source_sub.exists() and source_sub.stat().st_size > 0):
        log(f'{head} — LỖI: thiếu phụ đề {source_sub.name}, bỏ qua')
        return 'failed'

    from videotrans.configure import config as vt_config
    vt_config.init_run()
    from videotrans.util._srt_ass import set_ass_font
    from videotrans.util._srt_parse import get_subtitle_from_srt
    from videotrans.util._srt_wrap import simple_wrap

    work = workdir / '_original'
    work.mkdir(parents=True, exist_ok=True)

    # Ngắt dòng giống hệt pha lồng tiếng (_process_subtitles) để 26 video trông đồng bộ
    maxlen = maxlen_for(cfg, code)
    wrapped = work / f'{code}.srt'
    wrapped.write_text(''.join(
        f'{it["line"]}\n{it["time"]}\n{simple_wrap(it["text"].strip(), maxlen, code).strip()}\n\n'
        for it in get_subtitle_from_srt(str(source_sub))), encoding='utf-8')

    style_file = style_dir / f'{code}.json'
    style_file.write_text(json.dumps(style_for(cfg, code), ensure_ascii=False, indent=2),
                          encoding='utf-8')
    os.environ['PYVIDEOTRANS_ASS_JSON'] = str(style_file)
    try:
        ass_file = Path(set_ass_font(str(wrapped)))
    finally:
        os.environ.pop('PYVIDEOTRANS_ASS_JSON', None)
    if not ass_file.is_absolute():
        ass_file = work / ass_file.name
    if not ass_file.exists():
        log(f'{head} — LỖI: không tạo được file phụ đề .ass')
        return 'failed'

    enc = video_encoder(cfg)
    tmp = work / f'{video.stem}.mp4'
    task_log = logs_dir / f'original-{code}.log'

    log(f'{head} — nhúng phụ đề vào video gốc (giữ nguyên tiếng gốc) ...')
    started = time.time()
    # Chạy trong thư mục chứa .ass và gọi bằng tên file, khỏi phải escape đường dẫn
    # Windows (dấu : \ ') trong filter subtitles của ffmpeg.
    base_cmd = ['ffmpeg', '-y', '-hide_banner', '-nostdin', '-i', str(video),
                '-map', '0:v:0', '-map', '0:a?',
                '-vf', f"subtitles=filename='{ass_file.name}'",
                '-movflags', '+faststart']
    # Bộ mã hoá đã chọn, hỏng thì libx264. Ưu tiên chép nguyên luồng tiếng; codec tiếng
    # không hợp với mp4 thì mới mã hoá AAC.
    encoders = [enc['args']] + ([enc['fallback']] if enc['fallback'] != enc['args'] else [])
    for video_args, audio_args in ((v, a) for v in encoders
                                   for a in (['-c:a', 'copy'], ['-c:a', 'aac', '-b:a', '192k'])):
        cmd = base_cmd + video_args + audio_args + [str(tmp)]
        with task_log.open('a', encoding='utf-8') as fh:
            fh.write(f'\n$ {" ".join(cmd)}\n')
            rs = subprocess.run(cmd, cwd=str(ass_file.parent), stdout=fh, stderr=subprocess.STDOUT)
        if rs.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            break
        tmp.unlink(missing_ok=True)
    else:
        log(f'{head} — LỖI (chi tiết: {task_log})')
        return 'failed'

    dest = final_dir / f'{final_stem(lang, video.stem)}{tmp.suffix}'
    dest.unlink(missing_ok=True)
    link_final(tmp, dest, log)
    if cfg.get('cleanup_out', True) and dest.exists() and dest.stat().st_size > 0:
        shutil.rmtree(work, ignore_errors=True)
    log(f'{head} — xong sau {fmt_duration(time.time() - started)}')
    return 'ok'


def normalize_audio_track(video: Path, cfg: dict, log: Log, head: str) -> bool:
    """Chuẩn hoá âm lượng về chuẩn YouTube bằng loudnorm 2 lượt (đo rồi mới chỉnh).

    pyvideotrans trộn giọng và nhạc bằng amix nên biên độ bị chia đôi (-6 dB),
    video xuất ra nhỏ hơn hẳn bản gốc. Đo trước rồi chỉnh bằng độ lợi cố định
    (linear=true) để nhạc nền không bị bơm to nhỏ theo lời thoại.
    """
    target_i = cfg.get('loudnorm_i', -14)
    target_tp = cfg.get('loudnorm_tp', -1.5)
    target_lra = cfg.get('loudnorm_lra', 11)
    base = f'loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}'

    probe = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostats', '-i', str(video), '-vn',  # chỉ đo tiếng, khỏi giải mã hình
         '-af', f'{base}:print_format=json', '-f', 'null', '-'],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    blocks = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', probe.stderr, re.S)
    if not blocks:
        log(f'{head} — [CẢNH BÁO] không đo được âm lượng, giữ nguyên')
        return False
    try:
        m = json.loads(blocks[-1])
        if float(m['input_i']) < -70:  # gần như im lặng, chỉnh vào sẽ chỉ khuếch đại nhiễu
            return False
    except (ValueError, KeyError, json.JSONDecodeError):
        log(f'{head} — [CẢNH BÁO] kết quả đo âm lượng không đọc được, giữ nguyên')
        return False

    tmp = video.with_name(video.stem + '.norm' + video.suffix)
    applied = (f'{base}:measured_I={m["input_i"]}:measured_TP={m["input_tp"]}'
               f':measured_LRA={m["input_lra"]}:measured_thresh={m["input_thresh"]}'
               f':offset={m["target_offset"]}:linear=true')
    rs = subprocess.run(
        ['ffmpeg', '-y', '-hide_banner', '-nostats', '-loglevel', 'error', '-i', str(video),
         '-map', '0', '-c', 'copy', '-af', applied,
         '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
         '-movflags', '+faststart', str(tmp)],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    if rs.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        log(f'{head} — [CẢNH BÁO] chuẩn hoá âm lượng thất bại, giữ nguyên: '
            f'{rs.stderr.strip()[:160]}')
        return False
    tmp.replace(video)
    log(f'{head} — âm lượng {float(m["input_i"]):.1f} -> {target_i} LUFS')
    return True


def finalize(cfg: dict, log: Log, head: str, produced: Path, lang_out: Path,
             final_dir: Path, lang: dict, video_stem: str) -> None:
    """Chuẩn hoá âm lượng, đưa sang final/ với tên tiếng Việt, rồi dọn thư mục trung gian."""
    if cfg.get('normalize_audio'):
        # cli.py đã chuẩn hoá ngay trên tiếng trước khi ghép hình (PYVIDEOTRANS_LOUDNORM) thì để lại
        # loudnorm.json; không có (bản render cũ còn sót, hoặc đo lỗi) thì chuẩn hoá cả video như trước
        marker = lang_out / 'loudnorm.json'
        try:
            measured = float(json.loads(marker.read_text(encoding='utf-8'))['input_i'])
            log(f'{head} — âm lượng {measured:.1f} -> {cfg.get("loudnorm_i", -14)} LUFS')
        except (OSError, ValueError, KeyError):
            normalize_audio_track(produced, cfg, log, head)

    dest = final_dir / f'{final_stem(lang, video_stem)}{produced.suffix}'
    dest.unlink(missing_ok=True)  # bản cũ có thể là hardlink trỏ tới nội dung chưa chuẩn hoá
    link_final(produced, dest, log)

    # Xoá được an toàn: final/ là hardlink nên video vẫn còn nguyên dữ liệu
    if cfg.get('cleanup_out', True) and dest.exists() and dest.stat().st_size > 0:
        shutil.rmtree(lang_out, ignore_errors=True)


def link_final(source: Path, dest: Path, log: Log) -> None:
    """Hardlink kết quả sang thư mục final (không tốn thêm dung lượng), copy nếu không được."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return
    try:
        os.link(source, dest)
    except OSError:
        try:
            shutil.copy2(source, dest)
        except OSError as e:
            log(f'    [CẢNH BÁO] không tạo được {dest.name}: {e}')


# ---------------------------------------------------------------------------
# Xem trước style phụ đề
# ---------------------------------------------------------------------------
def make_previews(cfg: dict, langs: list, subs_dir: Path, preview_dir: Path,
                  style_dir: Path, log: Log) -> None:
    """Dựng 1 ảnh PNG 1080p cho mỗi ngôn ngữ, dùng đúng đường đi của bản render thật."""
    from videotrans.configure import config as vt_config
    vt_config.init_run()
    from videotrans.util._srt_ass import set_ass_font
    from videotrans.util._srt_wrap import simple_wrap

    preview_dir.mkdir(parents=True, exist_ok=True)
    work = preview_dir / '_work'
    work.mkdir(parents=True, exist_ok=True)

    for i, lang in enumerate(langs, start=1):
        code = lang['code']
        text = longest_cue(subs_dir / f'{code}.srt') or SAMPLE_TEXT.get(code) \
            or SAMPLE_TEXT.get(code[:2]) or SAMPLE_TEXT['en']
        wrapped = simple_wrap(text, maxlen_for(cfg, code), code)

        sample_srt = work / f'{code}.srt'
        sample_srt.write_text(f'1\n00:00:00,000 --> 00:00:05,000\n{wrapped}\n\n', encoding='utf-8')

        style_file = style_dir / f'{code}.json'
        style_file.parent.mkdir(parents=True, exist_ok=True)
        style_file.write_text(json.dumps(style_for(cfg, code), ensure_ascii=False, indent=2),
                              encoding='utf-8')
        os.environ['PYVIDEOTRANS_ASS_JSON'] = str(style_file)

        ass_file = Path(set_ass_font(str(sample_srt)))
        if not ass_file.is_absolute():
            ass_file = work / ass_file.name

        png = preview_dir / f'{code}.png'
        # Chạy trong thư mục chứa .ass và gọi bằng tên file, khỏi phải escape đường dẫn
        # Windows (dấu : \ ') trong filter subtitles của ffmpeg.
        cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
               '-f', 'lavfi', '-i', 'color=c=0x203040:s=1920x1080:d=1',
               '-vf', f"subtitles=filename='{ass_file.name}'",
               '-frames:v', '1', str(png)]
        rs = subprocess.run(cmd, cwd=str(ass_file.parent), capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
        status = 'ok' if png.exists() else f'LỖI: {rs.stderr.strip()[:200]}'
        log(f'  [{i}/{len(langs)}] {code:<6} {style_for(cfg, code)["Fontname"]:<24} {status}')

    os.environ.pop('PYVIDEOTRANS_ASS_JSON', None)
    log('')
    log(f'  Xem 25 ảnh tại: {preview_dir}')
    log('  Kiểm tra: chữ có bị ô vuông ▯ không, cỡ chữ, lề dưới, độ dày viền.')
    log('  Chỉnh trong dub_all.config.json -> subtitle_style, rồi chạy lại --preview-styles.')


def longest_cue(srt_file: Path) -> str:
    """Lấy dòng thoại dài nhất trong file SRT để xem trước trường hợp xấu nhất."""
    if not srt_file.exists():
        return ''
    blocks = re.split(r'\n\s*\n', srt_file.read_text(encoding='utf-8', errors='ignore').strip())
    best = ''
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        text = ' '.join(lines[2:])
        if len(text) > len(best):
            best = text
    return best


# ---------------------------------------------------------------------------
# Báo cáo
# ---------------------------------------------------------------------------
def write_report(cfg: dict, langs: list, trans_results: dict, dub_results: dict,
                 workdir: Path, video: Path, elapsed: float) -> Path:
    label = {'ok': 'Thành công', 'skipped': 'Bỏ qua (đã có)', 'failed': 'LỖI', '-': '-'}
    rows = []
    for lang in langs:
        code = lang['code']
        rows.append(
            f'| {lang.get("name", "")} | `{code}` | {lang["voice"]} | '
            f'{label.get(trans_results.get(code, "-"), "-")} | '
            f'{label.get(dub_results.get(code, "-"), "-")} | '
            f'`{final_stem(lang, video.stem)}.mp4` |'
        )

    report = workdir / 'report.md'
    report.write_text(
        f'# Báo cáo lồng tiếng — {video.name}\n\n'
        f'- Thời điểm: {time.strftime("%Y-%m-%d %H:%M:%S")}\n'
        f'- Tổng thời gian: {fmt_duration(elapsed)}\n'
        f'- Kênh dịch: `translate_type={cfg.get("translate_type")}` · '
        f'Kênh lồng tiếng: `tts_type={cfg.get("tts_type")}` · '
        f'Phụ đề: `subtitle_type={cfg.get("subtitle_type")}`\n'
        f'- Video thành phẩm: `{workdir / "final"}`\n\n'
        f'| Ngôn ngữ | Mã | Giọng đọc | Dịch | Lồng tiếng + Render | File |\n'
        f'|---|---|---|---|---|---|\n' + '\n'.join(rows) + '\n',
        encoding='utf-8')
    return report


# ---------------------------------------------------------------------------
# Chế độ menu — dùng khi bấm đúp vào LONG_TIENG.bat
# ---------------------------------------------------------------------------
SRT_EXTS = ('.srt', '.ass', '.vtt')


def ask_path(prompt: str, valid_exts: tuple) -> Path:
    while True:
        raw = input(prompt).strip().strip('"').strip("'")
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.exists():
            print(f'  Không tìm thấy file này, thử lại.')
            continue
        if valid_exts and path.suffix.lower() not in valid_exts:
            print(f'  Cần file có đuôi {" / ".join(valid_exts)}, bạn vừa đưa "{path.suffix}".')
            continue
        return path.resolve()


def run_menu(args, cfg: dict) -> argparse.Namespace:
    """Hỏi video / phụ đề / việc cần làm, trả về args đã điền đủ."""
    video = Path(args.video).resolve() if args.video else None
    srt = Path(args.srt).resolve() if args.srt else None

    # Nhận file kéo-thả vào file .bat, tự phân loại theo đuôi file
    for raw in args.paths:
        path = Path(raw.strip('"')).expanduser()
        if not path.exists():
            continue
        if path.suffix.lower() in SRT_EXTS:
            srt = srt or path.resolve()
        elif path.suffix.lower() in VIDEO_EXTS:
            video = video or path.resolve()

    print()
    print('=' * 62)
    print('   LỒNG TIẾNG HÀNG LOẠT — 1 video + 1 phụ đề  ->  25 ngôn ngữ')
    print('=' * 62)
    print('   Mẹo: kéo file từ Windows Explorer thả vào cửa sổ này rồi Enter')
    print()

    if video:
        print(f'   Video   : {video}')
    else:
        video = ask_path('   Video gốc      : ', VIDEO_EXTS)
    if srt:
        print(f'   Phụ đề  : {srt}')
    else:
        srt = ask_path('   Phụ đề gốc .srt: ', SRT_EXTS)

    codes = ', '.join(l['code'] for l in cfg.get('languages', []))
    print()
    print('   Chọn việc cần làm:')
    print('     1) Xem trước kiểu chữ phụ đề  (nên làm trước lần đầu)')
    print('     2) Chạy tất cả: dịch + lồng tiếng + nhúng phụ đề + render'
          ' (kèm video gốc có phụ đề gốc)')
    print('     3) Chỉ dịch phụ đề, chưa lồng tiếng')
    print('     4) Chỉ làm vài ngôn ngữ do tôi chọn')
    print('     0) Thoát')
    print()
    print(f'   ({len(cfg.get("languages", []))} ngôn ngữ trong cấu hình: {codes})')
    print()

    while True:
        choice = input('   Nhập số rồi Enter: ').strip()
        if choice == '0':
            sys.exit(0)
        if choice in ('1', '2', '3', '4'):
            break
        print('   Chỉ nhập 0, 1, 2, 3 hoặc 4.')

    args.video, args.srt = str(video), str(srt)
    if choice == '1':
        args.preview_styles = True
    elif choice == '3':
        args.only = 'translate'
    elif choice == '4':
        source_language = cfg.get('source_language', 'en')
        args.langs = input(f'   Nhập mã ngôn ngữ, cách nhau dấu phẩy (vd: ar,fi,da — '
                           f'thêm {source_language} để làm cả video gốc): ').strip()
    print()
    return args


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description='Lồng tiếng hàng loạt nhiều ngôn ngữ từ 1 video + 1 file phụ đề gốc.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Ví dụ:')[-1])
    p.add_argument('--video', default=None, help='Đường dẫn video gốc')
    p.add_argument('--srt', default=None, help='Đường dẫn file phụ đề ngôn ngữ gốc')
    p.add_argument('--menu', action='store_true',
                   help='Chế độ hỏi-đáp (dùng khi bấm đúp LONG_TIENG.bat)')
    p.add_argument('paths', nargs='*', default=[],
                   help='File kéo-thả vào .bat, tự nhận biết video hay phụ đề')
    p.add_argument('--workdir', default=None,
                   help='Thư mục làm việc (mặc định: <thư mục video>/dubbing_<tên video>)')
    p.add_argument('--config', default=str(DEFAULT_CONFIG), help='File cấu hình JSON')
    p.add_argument('--langs', default=None,
                   help='Chỉ xử lý các mã ngôn ngữ này, cách nhau bởi dấu phẩy. VD: ar,fi,da')
    p.add_argument('--only', choices=['translate', 'dub'], default=None,
                   help='Chỉ chạy 1 pha')
    p.add_argument('--preview-styles', action='store_true',
                   help='Chỉ dựng ảnh xem trước style phụ đề rồi thoát')
    # Nội bộ: tiến trình con tách nhạc nền chạy song song với bước dịch (start_separation)
    p.add_argument('--separate-worker', nargs=3, metavar=('VIDEO', 'SEP_DIR', 'MODEL'),
                   help=argparse.SUPPRESS)
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.separate_worker:
        return run_separate_worker(*args.separate_worker)
    cfg = load_config(Path(args.config))

    if args.menu or not (args.video and args.srt):
        args = run_menu(args, cfg)

    video = Path(args.video).expanduser().resolve()
    srt = Path(args.srt).expanduser().resolve()
    workdir = Path(args.workdir).expanduser().resolve() if args.workdir \
        else video.parent / f'dubbing_{video.stem}'

    source_language = cfg.get('source_language', 'en')
    langs = cfg.get('languages', [])
    # Video gốc chỉ nhúng phụ đề gốc; với --langs thì chỉ làm khi có ghi mã gốc (vd: en,ar)
    with_original = original_enabled(cfg)
    if args.langs:
        wanted = [c.strip() for c in args.langs.split(',') if c.strip()]
        with_original = with_original and source_language in wanted
        wanted = [c for c in wanted if c != source_language]
        by_code = {l['code']: l for l in langs}
        missing = [c for c in wanted if c not in by_code]
        if missing:
            sys.exit(f'[LỖI] --langs có mã không nằm trong config: {", ".join(missing)}')
        langs = [by_code[c] for c in wanted]
    if not langs and not with_original:
        sys.exit('[LỖI] Danh sách "languages" trong config đang rỗng.')

    subs_dir = workdir / 'subs'
    out_dir = workdir / 'out'
    final_dir = workdir / 'final'
    style_dir = workdir / '_styles'
    logs_dir = workdir / 'logs'
    for d in (subs_dir, out_dir, final_dir, style_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    import bao_cao_telegram
    # Lượt trước không có dòng kết thúc (đóng cửa sổ / tắt máy / treo phải tắt) -> gửi bù log lên Telegram
    previous_run = bao_cao_telegram.last_run(workdir / 'dub_all.log')
    log = Log(workdir / 'dub_all.log')
    keep_awake()
    started = time.time()
    try:
        log('')
        log('=' * 70)
        log(f'  Video      : {video}')
        log(f'  Phụ đề gốc : {srt}')
        log(f'  Thư mục    : {workdir}')
        log(f'  Ngôn ngữ   : {len(langs)} — {", ".join(l["code"] for l in langs)}')
        log(f'  Video gốc  : {"nhúng phụ đề " + source_language if with_original else "không làm"}')
        tts_type = int(cfg.get('tts_type', EDGE_TTS))
        log(f'  Giọng đọc  : {TTS_LABELS.get(tts_type, f"tts_type={tts_type}")}')
        log('=' * 70)
        bao_cao_telegram.report_interrupted(cfg, workdir, previous_run, log)

        log('')
        log('[0/2] Kiểm tra cấu hình...')
        validate(cfg, langs, video, srt, log)
        log('  OK')
        # Ngôn ngữ đổi số -> chữ trước khi đọc (chỉ chữ gửi cho OmniVoice, phụ đề giữ nguyên). Đặt vào
        # môi trường để cả tạo giọng trước (máy này) lẫn tiến trình lồng tiếng (cli.py) dùng chung.
        from videotrans.tts._dub_text import SPELL_ENV
        os.environ[SPELL_ENV] = ','.join(str(c) for c in (cfg.get('tts_spell_numbers') or []))
        if args.only != 'translate':
            warning = omnivoice_ref_warning(cfg)
            if warning:
                log(f'  [CẢNH BÁO] {warning}')

        if args.preview_styles:
            log('')
            log('[Xem trước] Dựng ảnh mẫu phụ đề...')
            if not (subs_dir / f'{source_language}.srt').exists():
                shutil.copy2(srt, subs_dir / f'{source_language}.srt')
            preview_langs = ([original_lang(cfg)] if with_original else []) + langs
            make_previews(cfg, preview_langs, subs_dir, workdir / 'preview', style_dir, log)
            return 0

        trans_results, dub_results = {}, {}

        # Tách nhạc nền không cần bản dịch: bắt đầu ngay, chạy song song với dịch + tạo giọng
        sep_thread = None
        if args.only != 'translate' and langs:
            try:
                sep_thread = start_separation(cfg, video, workdir / '_separate', logs_dir, log)
            except Exception as e:  # noqa: BLE001 - lỗi thì ngôn ngữ đầu tiên tự tách như cũ
                log(f'  [CẢNH BÁO] Không chạy trước được bước tách nhạc nền ({e})')

        if args.only != 'dub':
            log('')
            log('[1/2] Dịch phụ đề...')
            trans_results = phase_translate(cfg, langs, srt, subs_dir, log, logs_dir)

        if args.only != 'translate':
            log('')
            log('[2/2] Lồng tiếng + nhúng phụ đề + render...')
            pending = ([original_lang(cfg)] if with_original else []) + langs
            if any(not find_final_video(final_dir, l, video.stem) for l in pending):
                try:
                    cfg['_video_encoder'] = choose_video_encoder(cfg, video, workdir / '_bench', log)
                except Exception as e:  # noqa: BLE001 - đo lỗi thì dùng libx264 theo config
                    log(f'  [CẢNH BÁO] Không đo được tốc độ mã hoá ({e}), dùng libx264')
            tts = TtsPrefetch()
            if langs:
                try:
                    tts = start_tts_prefetch(cfg, langs, video, subs_dir, final_dir, workdir / '_tts', log,
                                             logs_dir)
                except Exception as e:  # noqa: BLE001 - tạo sẵn lỗi thì lúc render tự đọc như cũ
                    log(f'  [CẢNH BÁO] Tạo sẵn giọng lỗi ({e}), sẽ đọc trong lúc lồng tiếng.')
            if with_original:
                if not (subs_dir / f'{source_language}.srt').exists():
                    shutil.copy2(srt, subs_dir / f'{source_language}.srt')
                try:
                    dub_results[source_language] = phase_original(
                        cfg, video, subs_dir, workdir, final_dir, style_dir, log, logs_dir)
                except Exception as e:  # noqa: BLE001 - lỗi ở video gốc không được chặn 25 bản kia
                    log(f'  [gốc] {source_language} — LỖI: {e}')
                    dub_results[source_language] = 'failed'
            if sep_thread and sep_thread.is_alive():
                log('  Đang chờ tách nhạc nền + SFX xong...')
                sep_thread.join()
            if langs:
                dub_results.update(phase_dub(cfg, langs, video, subs_dir, out_dir, final_dir,
                                             style_dir, log, logs_dir, tts=tts))
                tts.join()
                # Đủ video mọi ngôn ngữ thì kho giọng tạo sẵn hết tác dụng (~200 MB/video)
                if cfg.get('cleanup_out', True) and all(find_final_video(final_dir, l, video.stem) for l in langs):
                    shutil.rmtree(workdir / '_tts', ignore_errors=True)

        elapsed = time.time() - started
        report_langs = ([original_lang(cfg)] if with_original else []) + langs
        report = write_report(cfg, report_langs, trans_results, dub_results, workdir, video,
                              elapsed)

        stats = dub_results or trans_results
        ok = sum(1 for v in stats.values() if v == 'ok')
        skipped = sum(1 for v in stats.values() if v == 'skipped')
        failed = [k for k, v in stats.items() if v == 'failed']

        summary = f'{fmt_duration(elapsed)} — {ok} thành công, {skipped} bỏ qua, {len(failed)} lỗi'
        log('')
        log('=' * 70)
        log(f'  Hoàn tất sau {summary}')
        if failed:
            log(f'  Ngôn ngữ lỗi: {", ".join(failed)} (chạy lại lệnh cũ để làm tiếp)')
        log(f'  Video thành phẩm : {final_dir}')
        log(f'  Báo cáo          : {report}')
        log('=' * 70)
        bao_cao_telegram.report_done(cfg, workdir, video, report, summary, failed, log)
        return 1 if failed else 0
    except KeyboardInterrupt:
        log('')
        log('[DỪNG] Đã huỷ. Chạy lại đúng lệnh cũ để tiếp tục từ chỗ dừng.')
        return 130
    except SystemExit as e:
        if e.code not in (0, None):  # validate(): cấu hình chưa hợp lệ, lỗi đã ghi vào log
            lines = bao_cao_telegram.last_run(workdir / 'dub_all.log')
            stop = next((i for i, l in enumerate(lines) if '[DỪNG]' in l), len(lines))
            bao_cao_telegram.report_crash(cfg, workdir, video, '\n'.join(
                l.split(' ', 1)[-1] for l in lines[stop:]) or str(e.code), log)
        raise
    except Exception as e:
        import traceback
        log('')
        log(f'[LỖI] Chương trình dừng vì lỗi: {e!r}')
        for line in traceback.format_exc().rstrip().splitlines():
            log(f'  {line}')
        bao_cao_telegram.report_crash(cfg, workdir, video, f'{e!r}', log)
        raise
    finally:
        log.close()


if __name__ == '__main__':
    sys.exit(main())
