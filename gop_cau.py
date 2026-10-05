# -*- coding: utf-8 -*-
"""
Gộp câu bị cắt đôi trước khi dịch + chia lại phụ đề hiển thị sau khi dịch (dub_all.py).

Phụ đề gốc (vd Remotion) ngắt câu theo độ dài dòng chứ không theo câu: "only ever see" | "scrambled
data.", có khi cắt giữa con số "$37." | "53 for the first 27 months". Dịch + đọc từng mảnh thì cả 25
ngôn ngữ đọc sai giá ("37 đô... 53 cho 27 tháng đầu"), câu cụt, mảnh 1 giây phải tua nhanh 1.4-1.6 lần.

  1) regroup: gộp các mảnh liền nhau thành 1 câu (cả câu chung 1 khung thời gian) -> AI dịch cả câu,
     giọng đọc liền một hơi.
  2) split_display: câu gộp dài quá 2 dòng thì chia lại thành nhiều phụ đề ngắn để hiển thị, thời gian
     chia theo số chữ. Chỉ phụ đề trên hình bị chia; giọng đọc vẫn theo câu gộp.
"""
import math
import re

# Câu kết thúc bằng các dấu này = hết câu / ngắt hơi rõ -> không gộp với câu sau
_TERMINAL = re.compile(r'[.!?…:;。！？：；"”»)\]]\s*$')
# "$37." + "53 for..." : dấu chấm giữa con số, không phải hết câu
_NUMBER_CUT = re.compile(r'\d\.$')
_STARTS_DIGIT = re.compile(r'^\s*\d')


def _flat(text: str) -> str:
    return ' '.join((text or '').split())


def ms_to_srt(ms: float) -> str:
    ms = max(0, int(round(ms)))
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def _cue(start: float, end: float, text: str) -> dict:
    return {'start_time': int(start), 'end_time': int(end), 'text': text,
            'time': f'{ms_to_srt(start)} --> {ms_to_srt(end)}'}


def is_punctuated(items: list) -> bool:
    """Phụ đề có chấm câu đàng hoàng không (Whisper không dấu câu thì gộp sẽ dính cả đoạn dài)"""
    texts = [_flat(it['text']) for it in items if _flat(it['text'])]
    return bool(texts) and sum(1 for t in texts if _TERMINAL.search(t)) >= 0.5 * len(texts)


def continues(cur: str, nxt: str) -> bool:
    """Câu cur chưa hết, nối tiếp sang câu nxt"""
    cur = _flat(cur)
    if not cur or not _flat(nxt):
        return False
    if _NUMBER_CUT.search(cur) and _STARTS_DIGIT.match(nxt):
        return True
    return not _TERMINAL.search(cur)


def regroup(items: list, max_gap_ms: int = 500, max_ms: int = 15000, max_chars: int = 220) -> tuple:
    """(câu sau khi gộp, số chỗ đã gộp). items: list từ get_subtitle_from_srt."""
    if not items or not is_punctuated(items):
        return [_cue(it['start_time'], it['end_time'], _flat(it['text'])) for it in items], 0
    out, merged = [], 0
    for it in items:
        text = _flat(it['text'])
        if out:
            last = out[-1]
            if (continues(last['text'], text)
                    and it['start_time'] - last['end_time'] <= max_gap_ms
                    and it['end_time'] - last['start_time'] <= max_ms
                    and len(last['text']) + len(text) < max_chars):
                # "$37." + "53 ..." -> "$37.53 ..." (dính liền, không chèn dấu cách vào giữa con số)
                glue = '' if _NUMBER_CUT.search(last['text']) and _STARTS_DIGIT.match(text) else ' '
                out[-1] = _cue(last['start_time'], max(last['end_time'], it['end_time']),
                               f'{last["text"]}{glue}{text}')
                merged += 1
                continue
        out.append(_cue(it['start_time'], it['end_time'], text))
    return out, merged


# Chỗ cắt đẹp: ngay sau dấu câu (ưu tiên), rồi tới khoảng trắng
_PUNCT_CUT = re.compile(r'[,.;:!?،؛、，。；：！？]\s*')


def _cut_points(text: str) -> list:
    """[(vị trí, điểm ưu tiên)] các chỗ có thể cắt; vị trí = độ dài phần trước"""
    points = {}
    for m in re.finditer(r'\s+', text):
        points[m.start()] = 1
    for m in _PUNCT_CUT.finditer(text):
        end = m.end()
        if 0 < end < len(text):
            points[end] = 3
    return sorted(points.items())


def _split_text(text: str, n: int, code: str) -> list:
    """Chia text thành n đoạn dài gần bằng nhau, cắt ở dấu câu / khoảng trắng gần nhất. Chữ Hán/Nhật
    không có chỗ cắt thì cắt theo ký tự; chữ khác (Thái...) không có chỗ cắt thì giữ nguyên."""
    points = _cut_points(text)
    cjk = code[:2] in ('zh', 'ja')
    cuts, size = [], len(text) / n
    for k in range(1, n):
        target, slack = k * size, size * 0.35
        lo = cuts[-1] + 1 if cuts else 1
        best = None
        for pos, weight in points:
            if pos < lo or abs(pos - target) > slack:
                continue
            score = weight - abs(pos - target) / max(slack, 1)
            if best is None or score > best[0]:
                best = (score, pos)
        if best:
            cuts.append(best[1])
        elif cjk and int(target) > lo:
            cuts.append(int(target))
    if not cuts:
        return [text]
    parts, prev = [], 0
    for c in cuts + [len(text)]:
        part = text[prev:c].strip()
        if part:
            parts.append(part)
        prev = c
    return parts


def split_display(items: list, maxlen: int, code: str, min_ms: int = 1000) -> tuple:
    """(phụ đề hiển thị, số câu đã chia). Câu dài hơn 2 dòng (maxlen ký tự/dòng) -> nhiều phụ đề
    ngắn, mỗi phụ đề >= min_ms, thời gian chia theo số chữ."""
    out, split = [], 0
    two_lines = 2 * maxlen + 4
    for it in items:
        text = _flat(it['text'])
        start, end = it['start_time'], it['end_time']
        n = min(math.ceil(len(text) / (2 * maxlen)), int((end - start) // min_ms))
        parts = _split_text(text, n, code) if len(text) > two_lines and n >= 2 else [text]
        if len(parts) < 2:
            out.append(_cue(start, end, text))
            continue
        split += 1
        total = sum(len(p) for p in parts)
        t = start
        for i, p in enumerate(parts):
            nxt = end if i == len(parts) - 1 else t + (end - start) * len(p) / total
            out.append(_cue(t, nxt, p))
            t = nxt
    return out, split


def write_srt(path, items: list) -> None:
    from pathlib import Path
    Path(path).write_text(''.join(f'{n}\n{it["time"]}\n{it["text"].strip()}\n\n'
                                  for n, it in enumerate(items, start=1)), encoding='utf-8')
