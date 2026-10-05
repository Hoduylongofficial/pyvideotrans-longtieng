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
# Thư mục "chữ để đọc" do AI viết (chu_doc.py): <thư mục>/<mã>.json = {"map": {câu phụ đề: câu để đọc}}
SPEAK_ENV = 'PYVIDEOTRANS_SPEAK_DIR'


def flat(text: str) -> str:
    """Gộp xuống dòng / khoảng trắng thừa: khoá tra bảng chữ để đọc"""
    return ' '.join((text or '').split())

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


_speak_cache = {}


def _speak_map(lang: str) -> dict:
    """{câu phụ đề (flat): câu để đọc} của ngôn ngữ này, đọc lại khi file đổi"""
    folder = os.environ.get(SPEAK_ENV, '').strip()
    if not folder:
        return {}
    path = Path(folder) / f'{(lang or "").lower()}.json'
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    hit = _speak_cache.get(path)
    if not hit or hit[0] != mtime:
        try:
            data = json.loads(path.read_text(encoding='utf-8')).get('map') or {}
            data = {flat(k): flat(v) for k, v in data.items() if flat(k) and flat(v)}
        except (OSError, ValueError, AttributeError):
            data = {}
        # tra ngược câu để đọc -> câu phụ đề; câu gửi đi đã qua phat_am.json nên ghi cả dạng đó
        back = {}
        for k, v in data.items():
            back[v] = back[flat(apply_lexicon(v, lang))] = k
        hit = _speak_cache[path] = (mtime, data, back)
    return hit[1]


def _display_of(spoken: str, lang: str) -> str:
    """Câu phụ đề của 1 câu để đọc do AI viết, '' nếu không có. Để chấm: Whisper hay ghi số bằng chữ số
    giống phụ đề hơn là bằng chữ."""
    if not _speak_map(lang):
        return ''
    folder = os.environ.get(SPEAK_ENV, '').strip()
    hit = _speak_cache.get(Path(folder) / f'{(lang or "").lower()}.json')
    return hit[2].get(flat(spoken), '') if hit else ''


def speak_text(text: str, lang: str, spell=None) -> str:
    """Chữ gửi cho TTS. spell=None: đọc danh sách ngôn ngữ đổi số từ biến môi trường."""
    out = _speak_map(lang).get(flat(text)) or text
    out = apply_lexicon(out, lang)
    langs = spell_langs() if spell is None else spell
    if (lang or '').lower() in langs or (lang or '').lower().split('-')[0] in langs:
        out = spell_numbers(out, lang)
    return out


# ---------------------------------------------------------------------------
# Chấm câu đọc
# ---------------------------------------------------------------------------
# Whisper ghi "10%" trong khi câu đọc là "zehn Prozent": khi chấm, đổi "số %" thành "số + chữ phần trăm"
# của ngôn ngữ đó (số đổi tiếp sang chữ ở spell_numbers). Tiếng Thổ đặt chữ trước số ("yüzde on").
PERCENT_WORD = {'de': 'prozent', 'es': 'por ciento', 'fr': 'pour cent', 'it': 'percento', 'pt': 'por cento',
                'nl': 'procent', 'sv': 'procent', 'da': 'procent', 'no': 'prosent', 'pl': 'procent',
                'cs': 'procent', 'ro': 'la sută', 'ru': 'процентов', 'uk': 'відсотків', 'fi': 'prosenttia',
                'id': 'persen', 'ms': 'peratus', 'fil': 'porsyento', 'tr': 'yüzde', 'el': 'τοις εκατό',
                'th': 'เปอร์เซ็นต์', 'ja': 'パーセント', 'ko': '퍼센트', 'zh': '百分之', 'ar': 'بالمئة',
                'hi': 'प्रतिशत', 'en': 'percent', 'vi': 'phần trăm'}
_PCT_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s?%')
_PCT_BEFORE_RE = re.compile(r'%\s?(\d+(?:[.,]\d+)?)')   # tiếng Thổ viết "%10"
# Ký hiệu tiền đứng sát số làm spell_numbers bỏ qua số đó ở 1 phía ("$43.20" vs Whisper "43.20")
_CURRENCY_RE = re.compile(r'[$€£¥₹₩]')


def _percent_words(text: str, lang: str) -> str:
    base = lang.split('-')[0]
    word = PERCENT_WORD.get(base)
    if not word:
        return text.replace('%', ' ')
    if base in ('tr', 'zh'):
        text = _PCT_BEFORE_RE.sub(lambda m: f' {word} {m.group(1)} ', text)
        return _PCT_RE.sub(lambda m: f' {word} {m.group(1)} ', text)
    return _PCT_RE.sub(lambda m: f' {m.group(1)} {word} ', text)


def _compare_form(text: str, lang: str) -> str:
    lang = (lang or '').lower()
    if lang.startswith('zh'):
        try:
            import zhconv
            text = zhconv.convert(text, 'zh-hans')   # Whisper hay ra giản thể dù đọc phồn thể
        except ImportError:
            pass
    text = unicodedata.normalize('NFKC', text)
    text = _percent_words(_CURRENCY_RE.sub(' ', text), lang)
    # num2words không có tiếng Philippines; người Philippines đọc số bằng tiếng Anh ("Box three")
    text = spell_numbers(text, 'en' if lang.startswith('fil') else lang).casefold()
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


# Câu Whisper hay tự bịa trên đoạn âm thanh ngắn (học từ phụ đề phim): "Danske tekster af ...",
# "谢谢观看" lặp 50 lần, "Untertitel im Auftrag des ZDF"... Không phải lỗi đọc.
_WHISPER_JUNK = re.compile(r'tekster af|tekstet av|untertitel|subtit|sottotitol|napisy|ondertitel|'
                           r'amara\.org|υπότιτλοι|субтитр|продолжение следует|谢谢观看|謝謝觀看|字幕|'
                           r'ご視聴ありがとう|thanks for watching|terima kasih telah menonton', re.I)


def scorable(expected: str, heard: str, lang: str) -> bool:
    """Whisper có chấm được câu này không. Không chấm (không đọc lại, không báo):
    - câu quá ngắn ("Sí", "Væk", "Weg", "安全"): Whisper nghe 1 âm tiết rất kém (ra "C.", hay tự bịa câu);
    - Whisper ra câu bịa quen thuộc của nó (lời cảm ơn / ghi công phụ đề) mà câu đọc không có."""
    a = _compare_form(expected, lang)
    if len(a) <= (2 if (lang or '').lower()[:2] in ('zh', 'ja') else 4):
        return False
    return not (heard and _WHISPER_JUNK.search(heard) and not _WHISPER_JUNK.search(expected))


def similarity(expected: str, heard: str, lang: str) -> float:
    """Điểm 0-1. Câu để đọc do AI viết (số bằng chữ) được chấm thêm với câu phụ đề gốc (số bằng chữ số),
    lấy điểm cao hơn: Whisper ghi số kiểu nào cũng không bị tính là đọc sai."""
    score = _similarity(expected, heard, lang)
    display = _display_of(expected, lang) if score < 1 else ''
    if display and display != expected:
        score = max(score, _similarity(display, heard, lang))
    return score


def _similarity(expected: str, heard: str, lang: str) -> float:
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
