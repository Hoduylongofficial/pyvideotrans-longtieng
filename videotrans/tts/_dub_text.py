# -*- coding: utf-8 -*-
"""Chữ đưa vào OmniVoice và cách chấm câu đọc (dub_all + _omnivoice_modal).

1) speak_text(text, lang): chữ thực sự gửi cho TTS. Phụ đề giữ nguyên, chỉ giọng đọc thấy bản này.
   - Bảng phát âm phat_am.json (gốc dự án): {"*": {"MEXC": "M E X C"}, "de": {...}} — thay nguyên
     từ, phân biệt hoa thường, cụm dài khớp trước.
   - Số -> chữ (num2words) cho các ngôn ngữ bật trong dub_all.config.json "tts_spell_numbers".
     Chỉ đổi số nguyên và số thập phân rõ ràng; "1,000", "3-5", "v2", "10:30", mã "007"... để nguyên
     (đổi sai nghĩa còn tệ hơn để model tự đọc).
2) similarity(expected, heard, lang): so câu yêu cầu với lời Whisper nghe lại (0..1), dùng để bắt
   câu đọc sót / lặp / sai thứ tiếng.
"""
import difflib
from decimal import Decimal
import json
import os
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEXICON_FILE = ROOT / 'phat_am.json'
SPELL_ENV = 'PYVIDEOTRANS_SPELL_NUMBERS'   # "de,ru,..." — dub_all truyền xuống tiến trình cli

# Mã pyvideotrans -> mã num2words (thiếu: hi, zh, fil, ms, el -> để nguyên số)
_N2W = {'pt-br': 'pt_BR', 'zh-tw': None, 'zh-cn': None}

_lexicon_cache = {}


def _n2w_lang(lang: str):
    lang = (lang or '').lower()
    if lang in _N2W:
        return _N2W[lang]
    try:
        from num2words import CONVERTER_CLASSES
    except ImportError:
        return None
    base = lang.split('-')[0]
    return base if base in CONVERTER_CLASSES else None


# Số đứng riêng: không dính chữ/số/dấu nối/gạch chéo/hai chấm/ký hiệu tiền ở hai bên, không đứng
# trước % (số + đơn vị phải chia theo đơn vị: "ein Prozent" chứ không "eins %"), không bắt đầu bằng 0
# (trừ chính số 0 hoặc 0,5), tối đa 7 chữ số. Phần thập phân 1-2 chữ số (3 chữ số thì nhiều khả năng
# là phân cách hàng nghìn kiểu Đức: 1.000).
_NUM_RE = re.compile(r'(?<![\w.,:/\-$€£¥])(0|[1-9]\d{0,6})(?:([.,])(\d{1,2}))?(?![\w:/\-]|[.,]\d|\s?%)')


def spell_numbers(text: str, lang: str) -> str:
    code = _n2w_lang(lang)
    if not code or not re.search(r'\d', text):
        return text
    from num2words import num2words

    def repl(m):
        whole, frac = m.group(1), m.group(3)
        try:
            # 1-2 chữ số sau dấu chấm/phẩy = thập phân, bất kể ngôn ngữ dùng dấu nào
            # (bản dịch AI hay giữ "1.5" kiểu Anh trong câu tiếng Đức)
            value = Decimal(f'{whole}.{frac}') if frac else int(whole)
            return num2words(value, lang=code)
        except Exception:  # noqa: BLE001 - num2words thiếu luật cho trường hợp này: giữ nguyên
            return m.group(0)

    return _NUM_RE.sub(repl, text)


def _load_lexicon() -> dict:
    try:
        mtime = LEXICON_FILE.stat().st_mtime
    except OSError:
        return {}
    if _lexicon_cache.get('mtime') != mtime:
        try:
            data = json.loads(LEXICON_FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        _lexicon_cache.update(mtime=mtime, data={k: v for k, v in data.items()
                                                 if not k.startswith('_') and isinstance(v, dict)})
    return _lexicon_cache['data']


def _lexicon_for(lang: str) -> dict:
    data = _load_lexicon()
    lang = (lang or '').lower()
    merged = {}
    for key in ('*', lang.split('-')[0], lang):
        merged.update({str(k): str(v) for k, v in (data.get(key) or {}).items() if str(k).strip()})
    return merged


def apply_lexicon(text: str, lang: str) -> str:
    lex = _lexicon_for(lang)
    if not lex:
        return text
    keys = sorted(lex, key=len, reverse=True)
    pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(k) for k in keys) + r')(?!\w)')
    return pattern.sub(lambda m: lex[m.group(0)], text)


def spell_langs() -> set:
    return {x.strip().lower() for x in os.environ.get(SPELL_ENV, '').split(',') if x.strip()}


def speak_text(text: str, lang: str, spell=None) -> str:
    """Chữ gửi cho TTS. spell=None: đọc danh sách ngôn ngữ đổi số từ biến môi trường."""
    out = apply_lexicon(text, lang)
    langs = spell_langs() if spell is None else spell
    if (lang or '').lower() in langs or (lang or '').lower().split('-')[0] in langs:
        out = spell_numbers(out, lang)
    return out


# ---------------------------------------------------------------------------
# Chấm câu đọc
# ---------------------------------------------------------------------------
def _compare_form(text: str, lang: str) -> str:
    lang = (lang or '').lower()
    if lang.startswith('zh'):
        try:
            import zhconv
            text = zhconv.convert(text, 'zh-hans')   # Whisper hay ra giản thể dù đọc phồn thể
        except ImportError:
            pass
    text = spell_numbers(unicodedata.normalize('NFKC', text), lang).casefold()
    # Bỏ dấu phụ (ş/ș, harakat Ả Rập...) và mọi thứ không phải chữ/số: Whisper ghi dấu câu, dấu
    # thanh, khoảng trắng theo kiểu riêng, không phải lỗi đọc
    text = unicodedata.normalize('NFKD', text)
    # Katakana -> hiragana: Whisper ghi 激混み hay 激コミ tuỳ lúc, cùng một cách đọc
    text = ''.join(chr(ord(ch) - 0x60) if 'ァ' <= ch <= 'ヶ' else ch for ch in text)
    return ''.join(ch for ch in text if unicodedata.category(ch)[0] in 'LN')


_LATIN_RUN = re.compile(r'[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ\'’.\-]*')


def _is_latin(ch: str) -> bool:
    return ch.isascii() or 'À' <= ch <= 'ɏ'


def heard_too_long(expected: str, heard: str, lang: str) -> bool:
    """Lời nghe được dài hơn gấp đôi câu: TTS lặp vòng, hoặc Whisper tự lặp / bịa thêm. Người gọi xem độ
    dài âm thanh để phân biệt (TTS lặp thì âm thanh cũng dài bất thường)."""
    return len(_compare_form(heard or '', lang)) > 2 * len(_compare_form(expected, lang)) + 10


def similarity(expected: str, heard: str, lang: str) -> float:
    a, b = _compare_form(expected, lang), _compare_form(heard or '', lang)
    if not a:
        return 1.0
    if not b:
        return 0.0
    if not (_LATIN_RUN.search(expected) and any(ch.isalpha() and not _is_latin(ch) for ch in expected)):
        return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    # Câu chữ bản xứ lẫn tên tiếng Anh (ja/th/ru/el... "Mario Kartに乗る"): TTS đọc tên đúng nhưng
    # Whisper ghi bằng chữ bản xứ (マリオカート) -> không so được giữa 2 hệ chữ. Chỉ chấm phần chữ bản xứ:
    # bao nhiêu phần của nó nghe thấy (bắt câu đọc sót), tên tiếng Anh bỏ qua.
    native = _compare_form(_LATIN_RUN.sub(' ', expected), lang)
    if not native:
        return 1.0
    heard_native = _compare_form(_LATIN_RUN.sub(' ', heard), lang)
    sm = difflib.SequenceMatcher(None, native, heard_native, autojunk=False)
    recall = sum(block.size for block in sm.get_matching_blocks()) / len(native)
    # Lặp vòng / nói thêm nhiều: tên tiếng Anh viết lại bằng chữ bản xứ dài cỡ bản gốc, nên lời nghe
    # được dài hơn gấp đôi cả câu là bất thường
    if len(b) > 2 * len(a) + 10:
        recall *= (2 * len(a) + 10) / len(b)
    return recall
