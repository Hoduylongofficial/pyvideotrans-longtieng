# -*- coding: utf-8 -*-
"""Gộp câu bị cắt đôi (gop_cau), chữ để đọc (chu_doc + _dub_text.speak_text) và cách chấm Whisper."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gop_cau  # noqa: E402
from videotrans.tts import _dub_text  # noqa: E402


def cue(start, end, text):
    return {'start_time': start, 'end_time': end, 'text': text}


SAMPLE = [
    cue(0, 2700, 'NordPass costs a dollar thirty-nine a\nmonth.'),
    cue(76700, 81300, "Your vault is encrypted on your own\ndevice, so NordPass's servers only ever see"),
    cue(81300, 82500, 'scrambled data.'),
    cue(285900, 290580, 'Through the special offer page linked\nbelow, NordPass Premium is $37.'),
    cue(290580, 294180, '53 for the first 27 months.'),
    cue(294833, 299193, 'That\'s two years plus three bonus months.'),
]


def test_regroup_merges_fragments_and_split_numbers():
    out, n = gop_cau.regroup(SAMPLE)
    assert n == 2
    texts = [o['text'] for o in out]
    assert "only ever see scrambled data." in texts[1]
    assert 'NordPass Premium is $37.53 for the first 27 months.' in texts[2]   # không chèn dấu cách vào số
    assert out[1]['time'] == '00:01:16,700 --> 00:01:22,500'


def test_regroup_respects_gap_and_unpunctuated_subs():
    far = [cue(0, 1000, 'and then'), cue(3000, 4000, 'later.'), cue(5000, 6000, 'Done.')]
    assert gop_cau.regroup(far)[1] == 0
    # Phụ đề không chấm câu (Whisper): không gộp, kẻo dính cả đoạn dài
    bare = [cue(i * 1000, i * 1000 + 900, f'word {i}') for i in range(10)]
    assert gop_cau.regroup(bare)[1] == 0


def test_split_display_keeps_short_and_splits_long():
    out, _ = gop_cau.regroup(SAMPLE)
    shown, n = gop_cau.split_display(out, 36, 'en')
    assert n >= 1
    for it in shown:
        assert len(it['text']) <= 2 * 36 + 10
    # thời gian liền mạch, nằm trong khung câu gộp
    parts = [s for s in shown if 76700 <= s['start_time'] < 82500]
    assert len(parts) == 2 and parts[0]['end_time'] == parts[1]['start_time'] and parts[-1]['end_time'] == 82500
    assert parts[0]['text'].endswith(',')   # cắt ở dấu phẩy


def test_scoring_percent_currency_short_and_hallucination():
    assert _dub_text.similarity('zehn Prozent Rabatt', '10% Rabatt', 'de') == 1.0
    assert _dub_text.similarity('Box three', 'Box 3', 'fil') == 1.0
    assert _dub_text.similarity('yüzde on indirim', '%10 indirim', 'tr') == 1.0
    assert _dub_text.similarity('Du sparst also $43.20', 'Du sparst also 43.20.', 'de') > 0.9
    assert not _dub_text.scorable('Væk', 'Danske tekster af Jesper Buhl', 'da')
    assert not _dub_text.scorable('安全', '谢谢观看', 'zh-tw')
    assert not _dub_text.scorable('Ούτε το NordPass μπορεί να σε επαναφέρει', 'Υπότιτλοι AUTHORWAVE', 'el')
    assert _dub_text.scorable('Heb je een team?', 'Happy and team.', 'nl')


def test_speak_map_used_for_tts_and_scoring(tmp_path, monkeypatch):
    sub = 'La versión empresarial tiene SOC 2 Type 2\ne ISO 27001'
    spoken = 'La versión empresarial tiene ese o ce dos Type dos e iso veintisiete mil uno'
    (tmp_path / 'es.json').write_text(json.dumps({'src': 'x', 'map': {_dub_text.flat(sub): spoken}}),
                                      encoding='utf-8')
    monkeypatch.setenv(_dub_text.SPEAK_ENV, str(tmp_path))
    assert _dub_text.speak_text(sub, 'es', spell=set()) == spoken
    assert _dub_text.speak_text('Hola', 'es', spell=set()) == 'Hola'
    # Whisper ghi bằng chữ số như phụ đề -> vẫn đúng
    assert _dub_text.similarity(spoken, 'La versión empresarial tiene SOC 2 Type 2 e ISO 27001', 'es') == 1.0


def test_needs_speaking():
    import chu_doc
    assert chu_doc.needs_speaking('$37.53 for 27 months')
    assert chu_doc.needs_speaking('SOC 2 Type 2')
    assert chu_doc.needs_speaking('choose EU or US')
    assert not chu_doc.needs_speaking('NordPass is the one I would pick.')
