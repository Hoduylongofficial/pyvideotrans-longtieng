# -*- coding: utf-8 -*-
"""
"Chữ để đọc" cho giọng lồng tiếng (dub_all.py) — phụ đề trên hình giữ nguyên, chỉ giọng đọc thấy bản này.

Log 10/2026 (video NordPass, 25 ngôn ngữ): OmniVoice đọc sai "$37.53", "$35.88", "$43.20" ở gần như mọi
ngôn ngữ (Whisper nghe ra "53 suéñe", "720 maanden", "20 centímetros"...); "SOC 2 Type 2", "ISO 27001",
"10%" cũng hay đọc lệch. num2words không biết tiền tệ, không chia cách/giống (tiếng Nga, Ba Lan...).

Sau khi dịch xong 1 ngôn ngữ: chọn các câu có số / ký hiệu / chữ viết tắt (needs_speaking), gọi AI 1 lượt
viết lại đúng như người bản xứ đọc to ("37 đô la 53 xu" bằng chữ, đúng ngữ pháp), lưu
subs/_chu_doc/<mã>.json = {"src": md5 phụ đề, "map": {câu phụ đề: câu để đọc}}.
videotrans/tts/_dub_text.speak_text tra bảng này trước khi gửi câu cho OmniVoice (tạo giọng trước + render).
Sửa tay được (giữ "src" để không bị tạo lại); phụ đề đổi thì tự tạo lại.
"""
import hashlib
import json
import re
from pathlib import Path

from videotrans.tts._dub_text import SPEAK_ENV, flat  # noqa: F401 - SPEAK_ENV để dub_all đặt biến môi trường

BATCH = 40

# Số, ký hiệu tiền / %, ký hiệu dùng như chữ, chữ viết tắt toàn chữ hoa (SOC, ISO, GDPR, EU)
_NEEDS = re.compile(r'\d|[$€£¥₹₩%&/+#@=~]|(?<![A-Za-z])[A-Z]{2,}(?![a-z])')

PROMPT = """You prepare {lang} subtitle lines to be read aloud by a {lang} text-to-speech voice.
Each line in <INPUT> has the form "id<TAB>text". Rewrite each text exactly as a native {lang} speaker would read it aloud:
- Write every number, price, currency amount, percentage, date, time, unit, version number and code out in {lang} words, in the {lang} script, with correct grammar (case, gender, number agreement). A price such as $37.53 becomes the way {lang} speakers say "thirty-seven dollars and fifty-three cents"; 27 months -> the words for twenty-seven months; codes like "ISO 27001" or "SOC 2 Type 2" -> how {lang} speakers read them aloud.
- Abbreviations and acronyms: write them as {lang} tech speakers actually pronounce them: letter by letter using {lang} letter names when people spell them out (SOC, CSV, GDPR, EU, 2FA are usually spelled), or as one word only when people really say them as a word. If unsure, spell letter by letter; never turn an acronym into an unrelated ordinary word. Symbols used as words (%, $, €, &, /, +) become {lang} words.
- Brand, product and app names stay exactly as written, except digits inside them, which you write as the word the name is pronounced with (1Password -> OnePassword).
- Change nothing else: same wording, same word order, same punctuation. Do not translate, shorten, explain or add anything.
Answer with JSON only, mapping each id to its rewritten text: {{"1": "...", "2": "..."}}, wrapped in <TRANSLATE_TEXT></TRANSLATE_TEXT>.

<INPUT>
{{batch_input}}
</INPUT>"""


def needs_speaking(text: str) -> bool:
    return bool(_NEEDS.search(text or ''))


_LINE = re.compile(r'^\s*"?(\d+)"?\s*:\s*"(.*)"\s*,?\s*$')


def _parse(raw: str) -> dict:
    """JSON {id: câu}. AI thỉnh thoảng trả JSON hỏng (dấu nháy trong câu, cụt cuối) -> đọc từng dòng
    "id": "câu" còn đọc được."""
    import thuat_ngu
    try:
        data = thuat_ngu._parse_json(raw)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()}
    except ValueError:
        pass
    out = {}
    for line in (raw or '').splitlines():
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2).replace('\\"', '"')
    return out


def _ask(cfg: dict, lang_name: str, code: str, chunk: list) -> dict:
    """{câu: câu để đọc} cho 1 lô. AI thỉnh thoảng trả thiếu / cụt -> hỏi lại riêng các câu còn thiếu
    (tối đa 2 lượt nữa)."""
    import thuat_ngu
    got, left = {}, list(chunk)
    for _ in range(3):
        listing = '\n'.join(f'{n}\t{t}' for n, t in enumerate(left, start=1))
        data = _parse(thuat_ngu._llm(cfg, PROMPT.format(lang=lang_name), listing, code))
        for n, t in enumerate(left, start=1):
            spoken = flat(str(data.get(str(n)) or ''))
            if spoken:
                got[t] = spoken
        left = [t for t in left if t not in got]
        if not left:
            break
    return got


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def build(cfg: dict, code: str, target_sub: Path, folder: Path) -> tuple:
    """Tạo / cập nhật subs/_chu_doc/<mã>.json. Trả về (số câu cần đọc riêng, số câu AI đã viết lại).
    Đã có và phụ đề không đổi thì giữ nguyên (kể cả bản người dùng sửa tay)."""
    from videotrans.util.help_srt import get_subtitle_from_srt
    from videotrans.translator._lang_utils import get_source_target_code

    path = folder / f'{code}.json'
    src = _md5(target_sub)
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))
        if cached.get('src') == src:
            return len(cached.get('map') or {}), len(cached.get('map') or {})
    except (OSError, ValueError, AttributeError):
        pass

    lines = list(dict.fromkeys(flat(it['text']) for it in get_subtitle_from_srt(str(target_sub))))
    todo = [t for t in lines if t and needs_speaking(t)]
    mapping = {}
    if todo:
        _, lang_name = get_source_target_code(show_target=code, translate_type=int(cfg.get('translate_type', 0)))
        for start in range(0, len(todo), BATCH):
            chunk = todo[start:start + BATCH]
            for t, spoken in _ask(cfg, lang_name, code, chunk).items():
                # Bỏ câu AI trả giống hệt / dài bất thường (bịa thêm): giữ nguyên câu phụ đề cho câu đó
                if spoken != t and len(spoken) <= 4 * len(t) + 40:
                    mapping[t] = spoken
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'src': src, 'map': mapping}, ensure_ascii=False, indent=2), encoding='utf-8')
    return len(todo), len(mapping)
