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
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


_force_utf8_console()

ROOT_DIR = Path(__file__).resolve().parent
CLI_PY = ROOT_DIR / 'cli.py'
DEFAULT_CONFIG = ROOT_DIR / 'dub_all.config.json'
EDGE_VOICE_JSON = ROOT_DIR / 'videotrans' / 'voicejson' / 'edge_tts.json'
PARAMS_JSON = ROOT_DIR / 'videotrans' / 'params.json'

EDGE_TTS = 0
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

    def __call__(self, msg: str = "") -> None:
        stamp = time.strftime('%H:%M:%S')
        # pha dịch chạy nhiều luồng cùng lúc, không khoá thì các dòng log chèn lẫn vào nhau
        with self._lock:
            print(msg, flush=True)
            self.fh.write(f'{stamp} {msg}\n')
            self.fh.flush()

    def close(self) -> None:
        self.fh.close()


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


def run_cli(cli_args: list, log: Log, task_log: Path, env: dict | None = None,
            quiet: bool = False) -> int:
    """Chạy cli.py, ghi toàn bộ output vào task_log, chỉ hiện dòng có ích lên màn hình.

    quiet=True: chỉ ghi vào task_log, không in ra màn hình. Dùng khi dịch song song
    nhiều ngôn ngữ, vì output của các tiến trình sẽ chèn lẫn vào nhau không đọc được.
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
        for line in proc.stdout:
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
        proc.wait()
    return proc.returncode


def attempt(cfg: dict, log: Log, head: str, task_log: Path, cli_args: list,
            succeeded, env: dict | None = None, quiet: bool = False) -> bool:
    """Chạy cli.py, thử lại vài lần nếu hỏng.

    Cần thiết cho chạy không người trông: model dịch thỉnh thoảng trả về rỗng,
    Edge-TTS có thể bị giới hạn tần suất.
    """
    attempts = max(1, int(cfg.get('retries', 2)))
    for n in range(1, attempts + 1):
        rc = run_cli(cli_args, log, task_log, env=env, quiet=quiet)
        if rc == 0 and succeeded():
            return True
        if n < attempts:
            log(f'{head} — hỏng lần {n}/{attempts}, thử lại sau 10s...')
            time.sleep(10)
    return False


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

    def translate_one(i: int, lang: dict, quiet: bool) -> tuple:
        code = lang['code']
        dest = subs_dir / f'{code}.srt'
        head = f'  [{i}/{total}] {code:<6} {lang.get("name", "")}'
        if dest.exists() and dest.stat().st_size > 0:
            log(f'{head} — đã có, bỏ qua')
            return code, 'skipped'

        log(f'{head} — đang dịch...')
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
        try:
            done = attempt(cfg, log, head, logs_dir / f'translate-{code}.log', cli_args,
                           lambda: produced.exists() and produced.stat().st_size > 0,
                           quiet=quiet)
        except Exception as e:  # noqa: BLE001 - một ngôn ngữ hỏng không được làm sập cả loạt
            log(f'{head} — LỖI: {e}')
            return code, 'failed'
        if done:
            produced.replace(dest)
            log(f'{head} — xong')
            return code, 'ok'
        log(f'{head} — LỖI (chi tiết: {logs_dir / f"translate-{code}.log"})')
        return code, 'failed'

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


def phase_dub(cfg: dict, langs: list, video: Path, subs_dir: Path, out_dir: Path,
              final_dir: Path, style_dir: Path, log: Log, logs_dir: Path) -> dict:
    source_language = cfg.get('source_language', 'en')
    source_sub = subs_dir / f'{source_language}.srt'
    sleep_between = float(cfg.get('sleep_between', 5))
    is_separate = bool(cfg.get('is_separate'))
    sep_dir = out_dir.parent / '_separate'
    results = {}

    if is_separate and not (sep_dir / 'instrument.wav').exists():
        log('  Giữ nhạc nền + SFX: sẽ tách nhạc khỏi giọng nói ở ngôn ngữ đầu tiên')
        log('  (chỉ tách 1 lần cho cả loạt, có thể mất vài phút với video dài)')

    for i, lang in enumerate(langs, start=1):
        code = lang['code']
        head = f'  [{i}/{len(langs)}] {code:<6} {lang.get("name", "")}'
        lang_out = out_dir / code
        if find_final_video(final_dir, lang, video.stem):
            log(f'{head} — đã hoàn thành, bỏ qua')
            results[code] = 'skipped'
            continue
        # Còn sót từ lần chạy bị ngắt giữa chừng: chỉ cần hoàn tất nốt
        leftover = find_output_video(lang_out, video.stem)
        if leftover:
            log(f'{head} — đã render sẵn, hoàn tất nốt')
            if is_separate:
                harvest_separated_audio(sep_dir, lang_out)
            finalize(cfg, log, head, leftover, lang_out, final_dir, lang, video.stem)
            results[code] = 'skipped'
            continue

        target_sub = subs_dir / f'{code}.srt'
        if code != source_language and not (target_sub.exists() and target_sub.stat().st_size > 0):
            log(f'{head} — LỖI: thiếu phụ đề {target_sub.name}, bỏ qua')
            results[code] = 'failed'
            continue

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
            '--voice_role', lang['voice'],
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
               'PYVIDEOTRANS_SUB_MAXLEN': str(maxlen_for(cfg, code))}
        if is_separate and cfg.get('uvr_model'):
            env['PYVIDEOTRANS_UVR_MODEL'] = str(cfg['uvr_model'])

        log(f'{head} — lồng tiếng {lang["voice"]} ...')
        started = time.time()
        done = attempt(cfg, log, head, logs_dir / f'dub-{code}.log', cli_args,
                       lambda: find_output_video(lang_out, video.stem) is not None, env=env)

        if is_separate:
            harvest_separated_audio(sep_dir, lang_out)
            if not (sep_dir / 'instrument.wav').exists():
                log(f'{head} — [CẢNH BÁO] tách nhạc nền thất bại, video này MẤT nhạc/SFX. '
                    f'Xem {logs_dir / f"dub-{code}.log"}')

        produced = find_output_video(lang_out, video.stem)
        if done and produced:
            finalize(cfg, log, head, produced, lang_out, final_dir, lang, video.stem)
            results[code] = 'ok'
            log(f'{head} — xong sau {fmt_duration(time.time() - started)}')
        else:
            results[code] = 'failed'
            log(f'{head} — LỖI (chi tiết: {logs_dir / f"dub-{code}.log"})')

        if i < len(langs) and sleep_between > 0:
            time.sleep(sleep_between)

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

    settings = vt_config.settings
    crf = str(settings.get('crf', 23))
    preset = settings.get('preset', 'medium')
    tmp = work / f'{video.stem}.mp4'
    task_log = logs_dir / f'original-{code}.log'

    log(f'{head} — nhúng phụ đề vào video gốc (giữ nguyên tiếng gốc) ...')
    started = time.time()
    # Chạy trong thư mục chứa .ass và gọi bằng tên file, khỏi phải escape đường dẫn
    # Windows (dấu : \ ') trong filter subtitles của ffmpeg.
    base_cmd = ['ffmpeg', '-y', '-hide_banner', '-nostdin', '-i', str(video),
                '-map', '0:v:0', '-map', '0:a?',
                '-vf', f"subtitles=filename='{ass_file.name}'",
                '-c:v', 'libx264', '-crf', crf, '-preset', preset, '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart']
    # Ưu tiên chép nguyên luồng tiếng; nếu codec tiếng không hợp với mp4 thì mới mã hoá AAC
    for audio_args in (['-c:a', 'copy'], ['-c:a', 'aac', '-b:a', '192k']):
        with task_log.open('a', encoding='utf-8') as fh:
            fh.write(f'\n$ {" ".join(base_cmd + audio_args)} {tmp}\n')
            rs = subprocess.run(base_cmd + audio_args + [str(tmp)], cwd=str(ass_file.parent),
                                stdout=fh, stderr=subprocess.STDOUT)
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
        ['ffmpeg', '-hide_banner', '-nostats', '-i', str(video),
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
    return p


def main() -> int:
    args = build_parser().parse_args()
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

    log = Log(workdir / 'dub_all.log')
    started = time.time()
    try:
        log('')
        log('=' * 70)
        log(f'  Video      : {video}')
        log(f'  Phụ đề gốc : {srt}')
        log(f'  Thư mục    : {workdir}')
        log(f'  Ngôn ngữ   : {len(langs)} — {", ".join(l["code"] for l in langs)}')
        log(f'  Video gốc  : {"nhúng phụ đề " + source_language if with_original else "không làm"}')
        log('=' * 70)

        log('')
        log('[0/2] Kiểm tra cấu hình...')
        validate(cfg, langs, video, srt, log)
        log('  OK')

        if args.preview_styles:
            log('')
            log('[Xem trước] Dựng ảnh mẫu phụ đề...')
            if not (subs_dir / f'{source_language}.srt').exists():
                shutil.copy2(srt, subs_dir / f'{source_language}.srt')
            preview_langs = ([original_lang(cfg)] if with_original else []) + langs
            make_previews(cfg, preview_langs, subs_dir, workdir / 'preview', style_dir, log)
            return 0

        trans_results, dub_results = {}, {}

        if args.only != 'dub':
            log('')
            log('[1/2] Dịch phụ đề...')
            trans_results = phase_translate(cfg, langs, srt, subs_dir, log, logs_dir)

        if args.only != 'translate':
            log('')
            log('[2/2] Lồng tiếng + nhúng phụ đề + render...')
            if with_original:
                if not (subs_dir / f'{source_language}.srt').exists():
                    shutil.copy2(srt, subs_dir / f'{source_language}.srt')
                try:
                    dub_results[source_language] = phase_original(
                        cfg, video, subs_dir, workdir, final_dir, style_dir, log, logs_dir)
                except Exception as e:  # noqa: BLE001 - lỗi ở video gốc không được chặn 25 bản kia
                    log(f'  [gốc] {source_language} — LỖI: {e}')
                    dub_results[source_language] = 'failed'
            if langs:
                dub_results.update(phase_dub(cfg, langs, video, subs_dir, out_dir, final_dir,
                                             style_dir, log, logs_dir))

        elapsed = time.time() - started
        report_langs = ([original_lang(cfg)] if with_original else []) + langs
        report = write_report(cfg, report_langs, trans_results, dub_results, workdir, video,
                              elapsed)

        stats = dub_results or trans_results
        ok = sum(1 for v in stats.values() if v == 'ok')
        skipped = sum(1 for v in stats.values() if v == 'skipped')
        failed = [k for k, v in stats.items() if v == 'failed']

        log('')
        log('=' * 70)
        log(f'  Hoàn tất sau {fmt_duration(elapsed)} — '
            f'{ok} thành công, {skipped} bỏ qua, {len(failed)} lỗi')
        if failed:
            log(f'  Ngôn ngữ lỗi: {", ".join(failed)} (chạy lại lệnh cũ để làm tiếp)')
        log(f'  Video thành phẩm : {final_dir}')
        log(f'  Báo cáo          : {report}')
        log('=' * 70)
        return 1 if failed else 0
    except KeyboardInterrupt:
        log('')
        log('[DỪNG] Đã huỷ. Chạy lại đúng lệnh cũ để tiếp tục từ chỗ dừng.')
        return 130
    finally:
        log.close()


if __name__ == '__main__':
    sys.exit(main())
