# -*- coding: utf-8 -*-
"""Tối ưu 10/2026 (log video hosting): viết ngắn câu đọc quá nhanh, render theo thứ tự sẵn sàng + chuẩn bị
tiếng trước, khoá render dùng chung, soát dịch / chấm Whisper bớt báo nhầm, model 9Router hết hạn mức."""
import base64
import io
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dub_all  # noqa: E402
from videotrans.tts import _dub_text  # noqa: E402
from videotrans.tts import _omnivoice_modal as om  # noqa: E402


def srt(path: Path, rows):
    path.write_text(''.join(f'{n}\n00:00:{a:02d},000 --> 00:00:{b:02d},000\n{t}\n\n'
                            for n, (a, b, t) in enumerate(rows, start=1)), encoding='utf-8')


# ---------------------------------------------------------------------------
# Soát bản dịch / chấm Whisper
# ---------------------------------------------------------------------------
def test_qa_brand_and_number_line_is_not_wrong_script(tmp_path):
    srt(tmp_path / 'en.srt', [(0, 3, 'SiteGround: $683.52.'), (4, 8, 'Hello there my good friends, welcome back.')])
    srt(tmp_path / 'ru.srt', [(0, 3, 'SiteGround: $683,52'), (4, 8, 'Hi there my dear friends, glad you are back')])
    issues, _ = dub_all.check_translation({}, tmp_path / 'en.srt', tmp_path / 'ru.srt', 'ru', ['SiteGround'])
    assert [(i[0], i[1]) for i in issues] == [(2, 'script')]   # câu tiếng Anh thật vẫn bị bắt


def test_qa_inflected_brand_is_kept(tmp_path):
    srt(tmp_path / 'en.srt', [(0, 3, 'Google cares about it.')])
    srt(tmp_path / 'cs.srt', [(0, 3, 'Záleží na tom Googlu.')])
    issues, _ = dub_all.check_translation({}, tmp_path / 'en.srt', tmp_path / 'cs.srt', 'cs', ['Google'])
    assert issues == []
    srt(tmp_path / 'cs.srt', [(0, 3, 'Záleží na tom vyhledávači.')])
    issues, _ = dub_all.check_translation({}, tmp_path / 'en.srt', tmp_path / 'cs.srt', 'cs', ['Google'])
    assert [i[1] for i in issues] == ['term']


def test_whisper_digits_vs_spelled_numbers_ko_zh():
    # Đọc đúng, Whisper ghi bằng chữ số (log qc-ko / qc-zh-tw 10/2026)
    assert _dub_text._similarity('SiteGround는 육백팔십삼 달러 오십이 센트입니다',
                                 '사이트 그라운은 683달러 52센트입니다.', 'ko') > 0.9
    assert _dub_text._similarity('Bluehost 是三十六個月，Namecheap 是二十四個月。',
                                 'Bluehost 是36个月Namecheap 是24个月', 'zh-tw') > 0.9
    assert _dub_text._zh_digits('兩點六九美元 三十六個月 二〇二六 一萬兩千') == '2.69美元 36個月 2026 12000'
    # Đọc cho TTS vẫn giữ luật chặt: số dính chữ Hàn không đổi (3개 đọc "세 개", không phải "삼")
    assert _dub_text.spell_numbers('3개', 'ko') == '3개'


# ---------------------------------------------------------------------------
# 9Router: model hết hạn mức được nhớ giữa các tiến trình
# ---------------------------------------------------------------------------
def test_model_cooldown(tmp_path, monkeypatch):
    from videotrans.translator import _openaicompat as oc
    monkeypatch.setattr(oc, 'COOLDOWN_FILE', tmp_path / 'cd.json')
    oc._mark_cooling('ninerouter', 'ag/opus', '[antigravity/opus] Unavailable (reset after 138h 20m 17s)')
    oc._mark_cooling('ninerouter', 'ag/flash', 'busy (reset after 30s)')        # ngắn: không ghi
    oc._mark_cooling('ninerouter', 'ag/pro', 'rate limited')                    # không có hạn: không ghi
    assert oc._cooling_models('ninerouter') == {'ag/opus'}
    assert oc._cooling_models('chatgpt') == set()
    until = json.loads((tmp_path / 'cd.json').read_text())['ninerouter']['ag/opus']
    assert 138 * 3600 < until - time.time() < 139 * 3600


# ---------------------------------------------------------------------------
# Khoá render dùng chung giữa các tiến trình
# ---------------------------------------------------------------------------
def test_render_slot_serializes(tmp_path, monkeypatch):
    from videotrans.task._stage_assemble import _RenderSlot
    monkeypatch.setenv('PYVIDEOTRANS_RENDER_SLOTS', f'{tmp_path}|1')
    first = _RenderSlot()
    got = {}

    def second():
        start = time.time()
        slot = _RenderSlot()
        got['waited'] = time.time() - start
        slot.release()

    t = threading.Thread(target=second)
    t.start()
    time.sleep(1.5)
    assert t.is_alive()          # chưa tới lượt
    first.release()
    t.join(10)
    assert got['waited'] >= 1.4
    monkeypatch.delenv('PYVIDEOTRANS_RENDER_SLOTS')
    assert _RenderSlot().fh is None   # không đặt biến: không chờ


# ---------------------------------------------------------------------------
# Tạo giọng: câu vẫn quá dài sau khi đọc lại theo khung -> viết ngắn + đọc lại
# ---------------------------------------------------------------------------
def _flac(seconds: float) -> str:
    x = (np.random.default_rng(0).standard_normal(int(om.SR * seconds)) * 0.3).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, x, om.SR, format='FLAC')
    return base64.b64encode(buf.getvalue()).decode()


def test_prefetch_shortens_lines_still_too_long(tmp_path, monkeypatch):
    ref = tmp_path / 'ref.wav'
    sf.write(str(ref), np.zeros(om.SR, dtype=np.float32), om.SR)
    monkeypatch.setattr(om, 'fixed_ref', lambda: (str(ref), 'ref'))
    monkeypatch.setattr(om, '_encode_ref', lambda p: 'x')
    monkeypatch.setattr(om, 'params', {'omnivoice_modal_url': 'http://x', 'omnivoice_modal_key': 'k'})
    sent = []

    def post(url, key, body, attempts=3):
        sent.append(body['items'])
        # 0.1 giây / ký tự; có duration thì đọc đúng thời lượng đó
        return {'audios': [_flac(it.get('duration') or len(it['text']) * 0.1) for it in body['items']]}

    monkeypatch.setattr(om, '_post', post)
    long_line = 'x' * 50
    asked = []

    def shorten(lang, rows):
        asked.append(rows)
        return {rows[0][0]: 'short'}

    ready = []
    res = om.prefetch(tmp_path / 'store', {'ar': [long_line, 'okay okay']},
                      slots={'ar': {long_line: 1.0, 'okay okay': 5.0}}, fit_ratio=1.2, log=lambda *a: None,
                      shorten=shorten, shorten_ratio=1.3, on_ready=ready.append, parallel=1)
    assert ready == ['ar']
    assert [r[1] for r in asked[0]] == [long_line] and asked[0][0][2] == 1.0
    assert res['ar'][4] == 1
    rid = om._ref_id(str(ref), 'ref')
    assert om._store_file(tmp_path / 'store', 'ar', rid, 'short').is_file()
    # lượt cuối: đọc câu mới (không còn đọc câu dài nữa)
    assert sent[-1] == [{'text': 'short', 'ref': 'r1', 'language': 'ar'}]


def test_shorten_lines_updates_subtitle_and_rejects_lost_numbers(tmp_path, monkeypatch):
    import thuat_ngu
    subs = tmp_path / 'subs'
    (subs / '_thuat_ngu').mkdir(parents=True)
    (subs / '_thuat_ngu' / 'terms.json').write_text(json.dumps({'terms': [{'term': 'Bluehost', 'keep': True}]}))
    srt(subs / 'en.srt', [(0, 3, 'Bluehost costs $3.99 a month.'), (4, 6, 'That is a lot of money really.'),
                          (7, 9, 'Short.')])
    srt(subs / 'ar.srt', [(0, 3, 'تكلفة Bluehost هي 3.99$ في الشهر الواحد فقط لا غير'),
                          (4, 6, 'هذا مبلغ كبير جدا جدا من المال حقا'), (7, 9, 'قصير')])
    calls = []

    def llm(cfg, prompt, text, code):
        calls.append(text)
        if 'too long for their time slot' in prompt:
            return '{"1": "Bluehost بـ 3.99$ شهريا", "2": "مبلغ كبير"}' if '3.99' in text.split('\n')[0] \
                else '{}'
        return '{"1": "Bluehost بثلاثة دولارات وتسعة وتسعين سنتا شهريا"}'

    monkeypatch.setattr(thuat_ngu, '_llm', llm)
    logs = tmp_path / 'logs'
    logs.mkdir()
    cfg = {'translate_type': 25, 'tts_type': dub_all.OMNIVOICE_TTS}
    rows = [('تكلفة Bluehost هي 3.99$ في الشهر الواحد فقط لا غير', 's1', 3.0, 5.5),
            ('هذا مبلغ كبير جدا جدا من المال حقا', 's2', 2.0, 3.5)]
    changed = dub_all.shorten_lines(cfg, 'ar', rows, subs, logs, lambda *a: None)
    assert changed == {rows[0][0]: 'Bluehost بـ 3.99$ شهريا', rows[1][0]: 'مبلغ كبير'}
    text = (subs / 'ar.srt').read_text(encoding='utf-8')
    assert 'Bluehost بـ 3.99$ شهريا' in text and 'مبلغ كبير' in text and 'قصير' in text
    assert '00:00:04,000 --> 00:00:06,000' in text                # giữ nguyên thời gian
    speak = json.loads((subs / '_chu_doc' / 'ar.json').read_text(encoding='utf-8'))
    assert speak['map'] == {'Bluehost بـ 3.99$ شهريا': 'Bluehost بثلاثة دولارات وتسعة وتسعين سنتا شهريا'}
    assert 'rutgon' in str(next(logs.glob('rutgon-ar.txt')))


def test_shorten_rejects_changed_numbers(tmp_path, monkeypatch):
    import thuat_ngu
    subs = tmp_path / 'subs'
    subs.mkdir()
    srt(subs / 'en.srt', [(0, 3, 'It costs $148.55 today.')])
    srt(subs / 'de.srt', [(0, 3, 'Das kostet heute ganze 148,55 $ auf einmal')])
    monkeypatch.setattr(thuat_ngu, '_llm', lambda *a: '{"1": "Heute 149 $"}')
    logs = tmp_path / 'logs'
    logs.mkdir()
    rows = [('Das kostet heute ganze 148,55 $ auf einmal', 's', 2.0, 4.0)]
    assert dub_all.shorten_lines({'translate_type': 25}, 'de', rows, subs, logs, lambda *a: None) == {}
    assert 'mất số' in (logs / 'rutgon-de.txt').read_text(encoding='utf-8')


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='cần ffmpeg')
def test_qc_report_has_audio_clip(tmp_path):
    flac = tmp_path / 'a.flac'
    sf.write(str(flac), np.zeros(om.SR, dtype=np.float32), om.SR)
    report = tmp_path / 'qc-hi.txt'
    dub_all.write_tts_qc_report(report, 'hi', [('cần', 'nghe', 0.5, flac)])
    assert 'file nghe: qc_audio/hi/01.mp3' in report.read_text(encoding='utf-8')
    assert (tmp_path / 'qc_audio' / 'hi' / '01.mp3').is_file()


# ---------------------------------------------------------------------------
# Lịch render: ngôn ngữ nào sẵn sàng trước làm trước
# ---------------------------------------------------------------------------
def test_phase_dub_renders_in_ready_order(tmp_path, monkeypatch):
    produced, order = set(), []
    monkeypatch.setattr(dub_all, 'find_final_video', lambda final_dir, lang, stem: None)
    monkeypatch.setattr(dub_all, 'find_output_video',
                        lambda d, stem: (d / 'x.mp4') if d.name in produced else None)
    monkeypatch.setattr(dub_all, 'video_encoder', lambda cfg: {'name': 'libx264', 'args': [], 'fallback': []})
    monkeypatch.setattr(dub_all, '_probe_video', lambda v: (0, 0, 60.0))
    monkeypatch.setattr(dub_all, 'render_parallel', lambda cfg, log=None: 1)
    monkeypatch.setattr(dub_all, 'display_sub', lambda *a: None)
    monkeypatch.setattr(dub_all, 'finalize', lambda *a: None)

    def attempt(cfg, log, head, task_log, cli_args, succeeded, env=None, quiet=False, stall_timeout=None):
        code = cli_args[cli_args.index('--target_language_code') + 1]
        order.append(code)
        assert os.environ['PYVIDEOTRANS_RENDER_SLOTS'].endswith('|1')
        produced.add(code)
        return True

    monkeypatch.setattr(dub_all, 'attempt', attempt)
    subs = tmp_path / 'subs'
    subs.mkdir()
    for code in ('ar', 'de', 'es'):
        (subs / f'{code}.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nx\n', encoding='utf-8')
    tts = dub_all.TtsPrefetch()
    tts.ready = {c: threading.Event() for c in ('ar', 'de', 'es')}
    tts.ready['de'].set()
    threading.Timer(1.0, tts.ready['ar'].set).start()
    threading.Timer(2.0, tts.ready['es'].set).start()
    langs = [{'code': c, 'name': c, 'voice': 'v'} for c in ('ar', 'de', 'es')]
    style = tmp_path / 'styles'
    style.mkdir()
    (tmp_path / 'logs').mkdir()
    cfg = {'tts_type': dub_all.OMNIVOICE_TTS, 'cleanup_out': False}
    res = dub_all.phase_dub(cfg, langs, tmp_path / 'v.mp4', subs, tmp_path / 'out', tmp_path / 'final',
                            style, lambda *a: None, tmp_path / 'logs', tts=tts)
    assert order == ['de', 'ar', 'es']
    assert res == {'de': 'ok', 'ar': 'ok', 'es': 'ok'}


def test_shorten_ai_call_does_not_block_gpu(tmp_path, monkeypatch):
    """Chờ AI viết ngắn câu tiếng Ả Rập thì GPU vẫn đọc ngôn ngữ khác (container không rảnh -> không tắt
    rồi khởi động lại, đỡ tiền)."""
    ref = tmp_path / 'ref.wav'
    sf.write(str(ref), np.zeros(om.SR, dtype=np.float32), om.SR)
    monkeypatch.setattr(om, 'fixed_ref', lambda: (str(ref), 'ref'))
    monkeypatch.setattr(om, '_encode_ref', lambda p: 'x')
    monkeypatch.setattr(om, 'params', {'omnivoice_modal_url': 'http://x', 'omnivoice_modal_key': 'k'})
    events = []

    def post(url, key, body, attempts=3):
        events.append(('post', body['items'][0]['language'], time.time()))
        return {'audios': [_flac(it.get('duration') or len(it['text']) * 0.1) for it in body['items']]}

    def shorten(lang, rows):
        events.append(('ask', lang, time.time()))
        time.sleep(1.5)
        return {rows[0][0]: 'short'}

    monkeypatch.setattr(om, '_post', post)
    long_line = 'x' * 50
    res = om.prefetch(tmp_path / 'store', {'ar': [long_line], 'de': ['hallo welt', 'guten tag']},
                      slots={'ar': {long_line: 1.0}, 'de': {'hallo welt': 5.0, 'guten tag': 5.0}},
                      fit_ratio=1.2, log=lambda *a: None, shorten=shorten, shorten_ratio=1.3, parallel=1,
                      order=['ar', 'de'])
    ask = next(t for k, lang, t in events if k == 'ask')
    de_posts = [t for k, lang, t in events if k == 'post' and lang == 'de']
    assert de_posts and de_posts[0] < ask + 1.0     # đọc tiếng Đức trong lúc chờ AI
    assert res['ar'][4] == 1 and res['de'][0] == 2
