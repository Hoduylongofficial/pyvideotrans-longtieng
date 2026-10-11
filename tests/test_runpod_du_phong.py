# -*- coding: utf-8 -*-
"""GPU RunPod dự phòng: Modal hết hạn mức tháng thì lượt đọc chuyển sang RunPod, đến hết tháng."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videotrans.tts import _omnivoice_modal as om  # noqa: E402

BODY = {'refs': {'r1': {'audio': 'x', 'text': 't'}},
        'items': [{'text': f'câu {i}', 'ref': 'r1', 'language': 'de'} for i in range(20)]}


class Resp:
    def __init__(self, status, data=None, text=''):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(om, 'params', {'omnivoice_modal_url': 'http://modal', 'omnivoice_modal_key': 'k',
                                       'runpod_endpoint_id': 'ep1', 'runpod_api_key': 'rk'})
    monkeypatch.setattr(om, 'MODAL_PAUSE_FILE', tmp_path / 'pause.json')
    monkeypatch.setattr(om.time, 'sleep', lambda s: None)
    calls = {'modal': 0, 'run': [], 'status': 0}
    state = {'modal': Resp(429, text='workspace spend limit reached')}

    def post(url, json=None, headers=None, timeout=None):
        if url.startswith('http://modal'):
            calls['modal'] += 1
            return state['modal']
        assert url == 'https://api.runpod.ai/v2/ep1/run' and headers['Authorization'] == 'Bearer rk'
        calls['run'].append(json['input'])
        return Resp(200, {'id': f'job{len(calls["run"]) - 1}'})

    def get(url, headers=None, timeout=None):
        calls['status'] += 1
        n = int(url.rsplit('job', 1)[1])
        items = calls['run'][n]['items']
        return Resp(200, {'status': 'COMPLETED', 'output': {'audios': [it['text'] for it in items], 'seconds': 1}})

    monkeypatch.setattr(om.requests, 'post', post)
    monkeypatch.setattr(om.requests, 'get', get)
    return calls, state


def test_modal_limit_switches_to_runpod_until_next_month(env):
    calls, _ = env
    out = om._post('http://modal', 'k', BODY)
    assert out['audios'] == [f'câu {i}' for i in range(20)]       # đúng thứ tự qua 2 job 16 + 4 câu
    assert [len(j['items']) for j in calls['run']] == [16, 4] and calls['run'][0]['op'] == 'tts'
    assert calls['modal'] == 1                                     # hết hạn mức: không thử lại Modal
    assert om.modal_paused()
    om._post('http://modal', 'k', BODY)                           # lượt sau đi thẳng RunPod
    assert calls['modal'] == 1
    assert om.time.time() < om._next_month_utc() <= om.time.time() + 32 * 86400


def test_modal_ok_never_touches_runpod(env):
    calls, state = env
    state['modal'] = Resp(200, {'audios': ['a'], 'seconds': 1})
    assert om._post('http://modal', 'k', BODY) == {'audios': ['a'], 'seconds': 1}
    assert not calls['run'] and not om.modal_paused()


def test_modal_flaky_pauses_only_briefly(env):
    calls, state = env
    state['modal'] = Resp(500, text='internal error')
    om._post('http://modal', 'k', BODY)
    assert calls['modal'] == 3 and len(calls['run']) == 2
    import json
    until = json.loads(om.MODAL_PAUSE_FILE.read_text(encoding='utf-8'))['until']
    assert until <= om.time.time() + om.MODAL_RETRY_MINUTES * 60 + 1


def test_without_runpod_modal_error_is_raised(env, monkeypatch):
    calls, _ = env
    monkeypatch.setattr(om, 'params', {'omnivoice_modal_url': 'http://modal', 'omnivoice_modal_key': 'k'})
    with pytest.raises(RuntimeError):
        om._post('http://modal', 'k', BODY)
    assert not calls['run'] and not om.modal_paused()
