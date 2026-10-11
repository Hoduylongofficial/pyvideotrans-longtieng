# -*- coding: utf-8 -*-
"""GPU vast.ai dự phòng: Modal hết hạn mức -> vast.ai trước, vast.ai chưa có máy / lỗi -> RunPod."""
import sys
import threading
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
                                       'runpod_endpoint_id': 'ep1', 'runpod_api_key': 'rk',
                                       'vast_endpoint': 'omnivoice', 'vast_endpoint_key': 'vk'})
    monkeypatch.setattr(om, 'MODAL_PAUSE_FILE', tmp_path / 'pause.json')
    monkeypatch.setattr(om.time, 'sleep', lambda s: None)
    monkeypatch.setitem(om._vast, 'cold_until', 0.0)
    monkeypatch.setattr(om, 'VAST_WAIT', 0.05)       # sleep đã tắt: không rút ngắn thì vòng chờ chạy đủ 180s
    lock = threading.Lock()
    calls = {'modal': 0, 'route': [], 'worker': [], 'runpod': []}
    state = {'ready': True, 'worker_status': 200}

    def post(url, json=None, headers=None, timeout=None, params=None):
        with lock:
            if url.startswith('http://modal'):
                calls['modal'] += 1
                return Resp(429, text='workspace spend limit reached')
            if url == om.VAST_ROUTE:
                assert headers['Authorization'] == 'Bearer vk' and json['endpoint'] == 'omnivoice'
                calls['route'].append(json['cost'])
                if not state['ready']:
                    return Resp(200, {'endpoint': 'omnivoice', 'status': 'Stopped', 'request_idx': 7})
                return Resp(200, {'url': 'https://1.2.3.4:5000', 'signature': 's', 'reqnum': 1,
                                  'cost': json['cost'], 'endpoint': 'omnivoice'})
            assert url == 'https://api.runpod.ai/v2/ep1/run'
            calls['runpod'].append(json['input'])
            return Resp(200, {'id': f'job{len(calls["runpod"]) - 1}'})

    def get(url, headers=None, timeout=None):
        items = calls['runpod'][int(url.rsplit('job', 1)[1])]['items']
        return Resp(200, {'status': 'COMPLETED', 'output': {'audios': [f'rp:{it["text"]}' for it in items]}})

    class Worker:
        def post(self, url, json=None, timeout=None):
            assert url == 'https://1.2.3.4:5000/tts' and json['auth_data']['signature'] == 's'
            with lock:
                calls['worker'].append(len(json['payload']['items']))
            if state['worker_status'] != 200:
                return Resp(state['worker_status'], text='busy')
            return Resp(200, {'audios': [f'vast:{it["text"]}' for it in json['payload']['items']], 'seconds': 2})

    monkeypatch.setattr(om.requests, 'post', post)
    monkeypatch.setattr(om.requests, 'get', get)
    monkeypatch.setattr(om, '_vast_http', lambda: Worker())
    return calls, state


def test_modal_limit_goes_to_vast_first(env):
    calls, _ = env
    out = om._post('http://modal', 'k', BODY)
    assert out['audios'] == [f'vast:câu {i}' for i in range(20)]     # đúng thứ tự qua 2 lượt 16 + 4
    assert sorted(calls['worker']) == [4, 16] and sorted(calls['route']) == [4, 16]
    assert not calls['runpod'] and calls['modal'] == 1 and out['provider'] == 'vast'


def test_vast_not_ready_falls_back_to_runpod(env):
    calls, state = env
    state['ready'] = False
    out = om._post('http://modal', 'k', BODY)
    assert out['audios'] == [f'rp:câu {i}' for i in range(20)]
    assert not calls['worker'] and len(calls['runpod']) == 2
    assert om._vast['cold_until'] > om.time.time()                   # lượt sau chỉ chờ ngắn


def test_vast_worker_errors_retry_then_runpod(env):
    calls, state = env
    state['worker_status'] = 503
    out = om._post('http://modal', 'k', BODY)
    assert out['audios'] == [f'rp:câu {i}' for i in range(20)]
    assert len(calls['worker']) == 6                                  # mỗi phần thử 3 máy rồi mới sang RunPod


def test_without_backups_modal_error_is_raised(env, monkeypatch):
    monkeypatch.setattr(om, 'params', {'omnivoice_modal_url': 'http://modal', 'omnivoice_modal_key': 'k'})
    with pytest.raises(RuntimeError):
        om._post('http://modal', 'k', BODY)
