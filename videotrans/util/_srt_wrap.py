# -*- coding: utf-8 -*-
import re
import unicodedata
from functools import lru_cache

from videotrans.configure import contants


def _cluster_end(text: str, i: int) -> int:
    """Trả về vị trí kết thúc của cụm ký tự bắt đầu tại i (ký tự gốc + dấu phụ đi kèm).

    Thái, Devanagari, Ả Rập... đặt dấu thanh/nguyên âm thành code point riêng nằm sau
    phụ âm gốc. Cắt dòng ngay giữa cụm sẽ đẩy dấu phụ sang đầu dòng sau thành ký tự
    mồ côi, ví dụ tiếng Thái "หนึ" + "่งแสน" thay vì "หนึ่ง" + "แสน".
    """
    j = i + 1
    while j < len(text) and unicodedata.category(text[j]) in ('Mn', 'Mc', 'Me'):
        j += 1
    return j


@lru_cache
def simple_wrap(text: str, maxlen: int = 15, language: str = "en") -> str:
    flag = [
        ",", ".", "?", "!", ";",
        "，", "。", "？", "；", "！", " "
    ]
    text = re.sub(r"\r?(\n|\\n)", ' ', text, flags=re.I).strip()
    _len = len(text)
    if _len < maxlen + 4:
        return text
    text_lilst = []
    current_text = ""
    offset = 2 if language[:2] in contants.CJK_LANG else 8
    maxlen = max(3, maxlen)
    offset = min(offset, maxlen // 2)

    i = 0
    while i < _len:
        current_text = current_text.lstrip()
        if i >= _len - offset:
            current_text += text[i:]
            break
        if len(current_text) < maxlen - offset:
            j = _cluster_end(text, i)
            current_text += text[i:j]
            i = j
            continue
        if maxlen - offset <= len(current_text) <= maxlen and text[i] in flag:
            current_text += text[i]
            i += 1
            text_lilst.append(current_text)
            current_text = ''
            continue
        raw_i = i
        for next_i in range(1, offset + 1):
            if i + next_i >= _len:
                break
            if text[i + next_i] in flag:
                pos_i = i + next_i + 1
                current_text += text[i:pos_i]
                raw_i = pos_i
                text_lilst.append(current_text)
                current_text = ''
                break
        if raw_i != i:
            i = raw_i
            continue
        j = _cluster_end(text, i)
        current_text += text[i:j]
        i = j
        if len(current_text) >= maxlen:
            text_lilst.append(current_text)
            current_text = ''

    if current_text and len(current_text) < maxlen / 3 and text_lilst:
        text_lilst[-1] += current_text
    elif current_text:
        text_lilst.append(current_text)
    return ("\n".join(text_lilst)).strip()
