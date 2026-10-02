# -*- coding: utf-8 -*-
"""
Bảng thuật ngữ cho bước dịch của dub_all.py — 1 thuật ngữ dịch giống nhau từ câu đầu tới câu cuối.

  1) extract_terms: gọi AI 1 lần trên toàn bộ phụ đề gốc, rút ra tên thương hiệu / mã coin / tên
     tính năng (giữ nguyên) và thuật ngữ chuyên ngành (cần dịch). Lưu <workdir>/subs/_thuat_ngu/terms.json.
  2) glossary_for: mỗi ngôn ngữ đích gọi AI 1 lượt nhỏ để dịch các thuật ngữ cần dịch.
     Lưu _thuat_ngu/<mã>.json = {"keep": [...], "translate": {"stop loss": "Stop-Loss", ...}}.
  3) dub_all truyền đường dẫn file đó qua biến môi trường PYVIDEOTRANS_GLOSSARY; prompt dịch
     (videotrans/translator/_base.py: dub_glossary_rule) chèn bảng vào mọi lượt dịch.

Các file JSON sửa tay được: sửa rồi xoá subs/<mã>.srt và chạy lại để dịch lại ngôn ngữ đó.
Chỉ chạy với kênh dịch AI (Gemini, DeepSeek, OpenRouter, 9Router...). Lỗi ở đây không chặn việc dịch.
"""
import json
import re
from pathlib import Path

GLOSSARY_ENV = 'PYVIDEOTRANS_GLOSSARY'
MAX_TERMS = 40

EXTRACT_PROMPT = """You are preparing a terminology list for translating the subtitles of ONE video into many languages.
Read the whole transcript inside <INPUT>. List at most {max_terms} items that must be rendered the SAME way every time they appear:
- brand, company, product, platform, app and feature/menu names; people's names; tickers and currency or unit codes (e.g. USDT, BTC, %)
- domain-specific terms and recurring key phrases of this topic (e.g. "stop loss", "leverage", "spot trading")
Skip ordinary words and anything that appears only once unless it is a name.
For each item return:
  "term": exactly as written in the transcript (same spelling and case),
  "keep": true only if it must stay exactly as written, in Latin letters, in every language: brand, company, product, platform and app names, tickers, currency/unit codes, promo codes, on-screen English UI labels. false for everything that should be translated or written the local way: domain terms, and also countries, cities, regions and people's names (each language uses its own established form, e.g. London -> Londres / ロンドン),
  "note": a very short meaning in this video, for the translator.
Answer with JSON only, in the form {{"terms": [{{"term": "...", "keep": true, "note": "..."}}]}}, wrapped in <TRANSLATE_TEXT></TRANSLATE_TEXT>.

<INPUT>
{{batch_input}}
</INPUT>"""

TRANSLATE_PROMPT = """You are a professional {lang} subtitle translator preparing a glossary for one video.
For each English term inside <INPUT> (with its meaning in this video), give the rendering a native {lang} speaker in this field would expect to hear in a dubbed video.
Use the established {lang} term; if native speakers really use the English term (common for some trading/tech words), keep it in English. Keep it short.
Answer with JSON only, mapping each term exactly as given to its {lang} rendering: {{"term": "rendering", ...}}, wrapped in <TRANSLATE_TEXT></TRANSLATE_TEXT>.

<INPUT>
{{batch_input}}
</INPUT>"""


def _llm(cfg: dict, prompt: str, text: str, target_code: str) -> str:
    """Gọi AI bằng đúng kênh dịch đang cấu hình (key, model, đổi model khi lỗi... dùng lại của kênh dịch)."""
    from videotrans import get_class
    from videotrans.translator._lang_utils import get_source_target_code
    from videotrans.translator._registry import _ID_NAME_DICT
    translate_type = int(cfg.get('translate_type', 0))
    _, lang_name = get_source_target_code(show_target=target_code, translate_type=translate_type)
    cls = get_class(translate_type, 'translator', _ID_NAME_DICT)
    engine = cls(text_list=[], target_language_name=lang_name, target_code=target_code,
                 source_code=cfg.get('source_language', 'en'), is_test=True, translate_type=translate_type)
    engine.prompt = prompt
    return engine._item_task(text) or ''


def _parse_json(raw: str):
    raw = re.sub(r'<think>.*?</think>', '', raw or '', flags=re.S)
    raw = re.sub(r'^\s*```(?:json)?|```\s*$', '', raw.strip(), flags=re.M).strip()
    start = min([i for i in (raw.find('{'), raw.find('[')) if i >= 0], default=-1)
    if start < 0:
        raise ValueError(f'AI không trả JSON: {raw[:200]}')
    return json.JSONDecoder().raw_decode(raw[start:])[0]


def available(cfg: dict) -> bool:
    from videotrans.translator._constants import AI_TRANS_CHANNELS
    return bool(cfg.get('translate_glossary', True)) and int(cfg.get('translate_type', 0)) in AI_TRANS_CHANNELS


def extract_terms(cfg: dict, source_sub: Path, folder: Path) -> list:
    """[{"term", "keep", "note"}] cho cả video, lưu cache terms.json"""
    cache = folder / 'terms.json'
    if cache.is_file():
        return json.loads(cache.read_text(encoding='utf-8')).get('terms', [])
    from videotrans.util.help_srt import get_subtitle_from_srt
    transcript = '\n'.join(it['text'].strip() for it in get_subtitle_from_srt(str(source_sub)) if it['text'].strip())
    data = _parse_json(_llm(cfg, EXTRACT_PROMPT.format(max_terms=MAX_TERMS), transcript, 'en'))
    terms, seen = [], set()
    for t in (data.get('terms', []) if isinstance(data, dict) else data):
        term = str((t or {}).get('term', '')).strip()
        # Chỉ nhận thuật ngữ có thật trong phụ đề (AI đôi khi tự đổi cách viết)
        if not term or term.casefold() in seen or term.casefold() not in transcript.casefold():
            continue
        seen.add(term.casefold())
        terms.append({'term': term, 'keep': bool(t.get('keep')), 'note': str(t.get('note', '')).strip()})
    folder.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({'terms': terms[:MAX_TERMS]}, ensure_ascii=False, indent=2), encoding='utf-8')
    return terms[:MAX_TERMS]


def glossary_for(cfg: dict, terms: list, code: str, folder: Path) -> Path:
    """File bảng thuật ngữ của 1 ngôn ngữ đích (tạo nếu chưa có)"""
    path = folder / f'{code}.json'
    if path.is_file():
        return path
    keep = [t['term'] for t in terms if t['keep']]
    need = [t for t in terms if not t['keep']]
    translate = {}
    if need:
        from videotrans.translator._lang_utils import get_source_target_code
        _, lang_name = get_source_target_code(show_target=code, translate_type=int(cfg.get('translate_type', 0)))
        listing = '\n'.join(f'- {t["term"]}' + (f' ({t["note"]})' if t['note'] else '') for t in need)
        data = _parse_json(_llm(cfg, TRANSLATE_PROMPT.format(lang=lang_name), listing, code))
        wanted = {t['term'].casefold(): t['term'] for t in need}
        for k, v in (data.items() if isinstance(data, dict) else []):
            term = wanted.get(str(k).strip().casefold())
            if term and str(v).strip():
                translate[term] = str(v).strip()
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'keep': keep, 'translate': translate}, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    return path


def keep_terms(folder: Path) -> list:
    """Thuật ngữ phải giữ nguyên (dùng cho bước soát bản dịch)"""
    try:
        return [t['term'] for t in json.loads((folder / 'terms.json').read_text(encoding='utf-8'))['terms']
                if t.get('keep')]
    except (OSError, ValueError, KeyError, TypeError):
        return []
