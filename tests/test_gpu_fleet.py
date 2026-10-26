# -*- coding: utf-8 -*-
"""GPU máy nhà (GPU Fleet, D:\\GPU Free) đọc trước, GPU thuê (Modal -> RunPod) chỉ đọc bù."""
import base64
import io
import sys
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videotrans.tts import _omnivoice_modal as om  # noqa: E402

PARAMS = {'omnivoice_modal_url': 'http://modal', 'omnivoice_modal_key': 'k',
          'fleet_url': 'http://fleet/', 'fleet_api_key': 'fk'}


def _flac(seconds: float = 1.0) -> bytes:
    x = (np.random.default_rng(0).standard_normal(int(om.SR * seconds)) * 0.3).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, x, om.SR, format='FLAC')
    return buf.getvalue()


class Resp:
    def __init__(self, status, data=None, content=b'', text=''):
        self.status_code, self._data, self.content, self.text = status, data, content, text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


class FakeFleet:
    """Server Fleet giả: câu nào có chữ 'treo' thì máy nhà không bao giờ đọc xong, 'hong' thì đọc lỗi."""

    def __init__(self):
        self.jobs, self.deleted, self.auth = {}, [], set()

    def __call__(self, method, url, headers=None, timeout=None, json=None, params=None):
        self.auth.add(headers['Authorization'])
        path = url.split('http://fleet', 1)[1]
        if method == 'POST' and path == '/v1/jobs':
            jid = f'j{len(self.jobs)}'
            self.jobs[jid] = json
            return Resp(200, {'job_id': jid, 'total': len(json['items'])})
        if method == 'GET' and path == '/v1/stats':
            return Resp(200, {'workers': {'ready': 1, 'working': 2, 'offline': 9}, 'open_tasks': {}})
        if method == 'DELETE':
            self.deleted.append(path.rsplit('/', 1)[1])
            return Resp(204)
        jid = path.split('/')[3]
        items = self.jobs[jid]['items']
        if path.endswith('/audio'):
            return Resp(200, content=b'flac:' + items[int(path.split('/')[5])]['text'].encode())

        def st(it):
            return 'leased' if 'treo' in it['text'] else 'failed' if 'hong' in it['text'] else 'done'
        states = [{'index': i, 'status': st(it)} for i, it in enumerate(items)]
        busy = any(s['status'] == 'leased' for s in states)
        return Resp(200, {'job_id': jid, 'status': 'processing' if busy else 'done', 'total': len(items),
                          'done': 0, 'failed': 0, 'items': states})


def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(om, 'params', dict(PARAMS))
    monkeypatch.setattr(om, 'MODAL_PAUSE_FILE', tmp_path / 'pause.json')
    monkeypatch.setattr(om, 'FLEET_POLL_S', 0)
    monkeypatch.setattr(om, 'FLEET_STALL_S', 0.3)
    monkeypatch.setattr(om, '_fleet_stats', {'at': 0.0, 'online': 0})
    fleet = FakeFleet()
    monkeypatch.setattr(om.requests, 'request', fleet)
    modal = []

    def post_modal(url, key, body, attempts=3):
        modal.append([it['text'] for it in body['items']])
        return {'audios': [base64.b64encode(b'modal:' + it['text'].encode()).decode() for it in body['items']]}

    monkeypatch.setattr(om, '_post_modal', post_modal)
    return fleet, modal


def _decode(out):
    return [base64.b64decode(a).decode() if a else '' for a in out['audios']]


def test_fleet_reads_all_lines_in_order_and_skips_empty(monkeypatch, tmp_path):
    fleet, modal = _env(monkeypatch, tmp_path)
    body = {'refs': {'r1': {'audio': 'x', 'text': 't'}}, 'asr': True,
            'items': [{'text': 'một', 'ref': 'r1'}, {'text': '  '}, {'text': 'hai', 'duration': 1.5}]}
    out = om._post_shared('http://modal', 'k', body)
    assert _decode(out) == ['flac:một', '', 'flac:hai']
    assert out['lines'] == {'fleet': 2} and not modal
    sent = fleet.jobs['j0']
    assert [it['text'] for it in sent['items']] == ['một', 'hai'] and sent['items'][1]['duration'] == 1.5
    assert 'asr' not in sent and sent['refs'] == body['refs'] and fleet.auth == {'Bearer fk'}


def test_stalled_and_failed_lines_go_to_paid_gpu(monkeypatch, tmp_path):
    fleet, modal = _env(monkeypatch, tmp_path)
    body = {'items': [{'text': 'a'}, {'text': 'b treo'}, {'text': 'c hong'}, {'text': 'd'}]}
    out = om._post_shared('http://modal', 'k', body)
    assert _decode(out) == ['flac:a', 'modal:b treo', 'modal:c hong', 'flac:d']
    assert modal == [['b treo', 'c hong']]                 # GPU thuê chỉ đọc câu máy nhà bỏ dở / lỗi
    assert out['lines'] == {'fleet': 2, 'modal': 2}
    assert fleet.deleted == ['j0']                         # huỷ job để máy nhà khỏi đọc tiếp
    assert om.fleet_online() == 0                          # server còn báo 3 máy nhưng tạm coi như 0


def test_fleet_down_everything_to_paid(monkeypatch, tmp_path):
    _, modal = _env(monkeypatch, tmp_path)
    monkeypatch.setattr(om.time, 'sleep', lambda s: None)
    monkeypatch.setattr(om.requests, 'request', lambda *a, **k: Resp(401))
    out = om._post_shared('http://modal', 'k', {'items': [{'text': 'a'}, {'text': 'b'}]})
    assert _decode(out) == ['modal:a', 'modal:b'] and out['lines'] == {'fleet': 0, 'modal': 2}


def test_fleet_online_counts_ready_and_working_and_caches(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    assert om.fleet_online() == 3
    monkeypatch.setattr(om.requests, 'request', lambda *a, **k: Resp(500))
    assert om.fleet_online() == 3                           # còn trong 30 giây: không hỏi lại


# ---------------------------------------------------------------------------
# prefetch(): chia lô giữa máy nhà và GPU thuê
# ---------------------------------------------------------------------------
def _prefetch_env(monkeypatch, tmp_path, online, fleet_delay=0.0):
    ref = tmp_path / 'ref.wav'
    sf.write(str(ref), np.zeros(om.SR, dtype=np.float32), om.SR)
    monkeypatch.setattr(om, 'fixed_ref', lambda: (str(ref), 'ref'))
    monkeypatch.setattr(om, '_encode_ref', lambda p: 'x')
    monkeypatch.setattr(om, 'params', dict(PARAMS))
    monkeypatch.setattr(om, 'fleet_online', lambda: online)
    audio = base64.b64encode(_flac()).decode()
    got = {'fleet': [], 'modal': []}
    lock = threading.Lock()

    def fleet(body):
        if fleet_delay:
            time.sleep(fleet_delay)
        with lock:
            got['fleet'].append(body['items'][0]['language'])
        return {'audios': [audio] * len(body['items']), 'provider': 'fleet'}

    def modal(url, key, body, attempts=3):
        with lock:
            got['modal'].append(body['items'][0]['language'])
        return {'audios': [audio] * len(body['items'])}

    monkeypatch.setattr(om, '_post_fleet', fleet)
    monkeypatch.setattr(om, '_post', modal)
    jobs = {lang: [f'{lang} câu {i}' for i in range(70)] for lang in ('de', 'fr', 'it', 'es')}   # 3 lô / ngôn ngữ
    logs, ready = [], []
    res = om.prefetch(tmp_path / 'store', jobs, parallel=2, log=logs.append, on_ready=ready.append)
    assert sorted(ready) == sorted(jobs) and all(v[0] == 70 for v in res.values())
    return got, logs


def test_prefetch_fleet_keeps_up_paid_gpu_idle(monkeypatch, tmp_path):
    got, logs = _prefetch_env(monkeypatch, tmp_path, online=2)
    assert len(got['fleet']) == 12 and not got['modal']
    assert any('máy nhà 280' in l and '~$0.20' in l for l in logs)
    assert any('GPU máy nhà (Fleet): 2 máy online' in l for l in logs)


def test_prefetch_no_home_gpu_online_uses_paid_only(monkeypatch, tmp_path):
    got, logs = _prefetch_env(monkeypatch, tmp_path, online=0)
    assert not got['fleet'] and len(got['modal']) == 12
    assert any('Modal 280' in l for l in logs)


def test_prefetch_paid_gpu_helps_only_near_languages_when_fleet_slow(monkeypatch, tmp_path):
    monkeypatch.setattr(om, 'PAID_AFTER_S', 0.2)
    monkeypatch.setattr(om, 'PAID_LANGS', 1)
    got, _ = _prefetch_env(monkeypatch, tmp_path, online=1, fleet_delay=0.4)
    assert got['fleet'] and got['modal'] and len(got['fleet']) + len(got['modal']) == 12
    # máy nhà 1 máy = 2 lô cùng lúc, lô đầu hàng (de) do máy nhà nhận trước khi GPU thuê được phép nhận
    assert got['fleet'][:2] == ['de', 'de']


def test_without_fleet_config_behaves_as_before(monkeypatch, tmp_path):
    monkeypatch.setattr(om, 'fleet_configured', lambda: False)
    got, logs = _prefetch_env(monkeypatch, tmp_path, online=5)
    assert not got['fleet'] and len(got['modal']) == 12
    assert not any('Fleet' in l for l in logs)
