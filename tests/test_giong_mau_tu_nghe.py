# -*- coding: utf-8 -*-
"""Giọng mẫu cố định bỏ trống lời: Whisper trên Modal nghe 1 lần, máy nhà GPU Fleet nhận kèm lời."""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videotrans.tts import _omnivoice_modal as om  # noqa: E402


class Resp:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


def _setup(monkeypatch, tmp_path, text='', status=200, heard='Over the last couple of months.'):
    wav = tmp_path / 'giong_mau_omnivoice.wav'
    sf.write(str(wav), np.zeros(om.SR, dtype=np.float32) + 0.01, om.SR)
    monkeypatch.setattr(om, 'params', {'omnivoice_modal_url': 'http://modal/', 'omnivoice_modal_key': 'k',
                                       'omnivoice_ref_wav': str(wav), 'omnivoice_ref_text': text})
    monkeypatch.setattr(om, 'MODAL_PAUSE_FILE', tmp_path / 'pause.json')
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))
        return Resp(status, {'texts': [heard]})
    monkeypatch.setattr(om.requests, 'post', post)
    return wav, calls


def test_empty_text_heard_once_and_cached(monkeypatch, tmp_path):
    wav, calls = _setup(monkeypatch, tmp_path)
    assert om.fixed_ref() == (str(wav), 'Over the last couple of months.')
    assert om.fixed_ref()[1] == 'Over the last couple of months.'
    assert [c[0] for c in calls] == ['http://modal/asr']
    assert calls[0][1]['items'][0]['audio']
    assert (tmp_path / 'giong_mau_omnivoice.loi_tu_nghe.txt').is_file()


def test_typed_text_not_sent_to_whisper(monkeypatch, tmp_path):
    _, calls = _setup(monkeypatch, tmp_path, text=' Hello there. ')
    assert om.fixed_ref()[1] == 'Hello there.'
    assert calls == []


def test_new_ref_file_heard_again(monkeypatch, tmp_path):
    wav, calls = _setup(monkeypatch, tmp_path)
    om.fixed_ref()
    sf.write(str(wav), np.zeros(om.SR * 2, dtype=np.float32) + 0.02, om.SR)
    om.fixed_ref()
    assert len(calls) == 2


def test_whisper_error_sends_empty_and_retries_later(monkeypatch, tmp_path):
    _, calls = _setup(monkeypatch, tmp_path, status=500)
    assert om.fixed_ref()[1] == ''
    assert not (tmp_path / 'giong_mau_omnivoice.loi_tu_nghe.txt').exists()
    om.fixed_ref()
    assert len(calls) == 2


def test_modal_paused_skips_whisper(monkeypatch, tmp_path):
    _, calls = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(om, 'modal_paused', lambda: 'hết hạn mức')
    assert om.fixed_ref()[1] == ''
    assert calls == []
