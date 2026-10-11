# -*- coding: utf-8 -*-
"""
OmniVoice TTS trên GPU serverless của RunPod — dự phòng khi Modal hết hạn mức tháng.

Cùng model, cùng cách đọc với modal_tts/omnivoice_modal.py (sửa bên đó thì sửa cả ở đây), chỉ khác
đường gọi: endpoint "queue" của RunPod, máy khách gửi POST https://api.runpod.ai/v2/<endpoint>/run
  {"input": {"op": "tts", "refs": {...}, "items": [...], "num_step": 32, "asr": false}}
rồi hỏi /status/<job> đến khi xong; "output" giống hệt JSON mà /tts của Modal trả về.
  {"input": {"op": "asr", "items": [{"audio": "<base64>", "language": "de"}]}} -> {"texts": [...]}
Khoá = API key RunPod (header Authorization), không cần key riêng như Modal.

Build: RunPod tự build runpod_tts/Dockerfile từ GitHub mỗi khi tạo Release mới.
vast.ai Serverless dùng lại file này qua vast_tts/model_server.py (import rồi gọi handler()).
"""
import base64
import hashlib
import io
import os
import threading
import time

import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice

MODEL_DIR = os.environ.get('OMNIVOICE_MODEL_DIR', '/models/OmniVoice')
BATCH = 16            # số câu đọc cùng lúc trên GPU
LANG_ALIASES = {'ar': 'arb'}
WHISPER_LANG = {'fil': 'tl', 'zh-tw': 'zh', 'zh-cn': 'zh'}
ASR_MODEL = 'openai/whisper-large-v3-turbo'

# Nạp model 1 lần khi máy bật; các job sau dùng lại
model = OmniVoice.from_pretrained(MODEL_DIR, device_map='cuda:0', dtype=torch.float16)
prompts = {}          # cache giọng mẫu: cùng 1 file mẫu thì chỉ mã hoá 1 lần
asr_lock = threading.Lock()


def _prompt(ref_b64: str, ref_text: str):
    key = hashlib.sha1((ref_b64 + '|' + (ref_text or '')).encode()).hexdigest()
    if key not in prompts:
        wav, sr = sf.read(io.BytesIO(base64.b64decode(ref_b64)), dtype='float32', always_2d=True)
        prompts[key] = model.create_voice_clone_prompt(
            (torch.from_numpy(wav.T.copy()), sr), ref_text=ref_text or None)
        if len(prompts) > 512:
            prompts.pop(next(iter(prompts)))
    return prompts[key]


def _language(code):
    if not code:
        return None
    ids = model.supported_language_ids()
    code = LANG_ALIASES.get(code.lower(), code)
    for c in (code, code.lower(), code.split('-')[0].lower()):
        if c in ids:
            return c
    return None


def _synthesize(refs: dict, items: list, num_step: int) -> list:
    out = []
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        ps = [_prompt(refs[it['ref']]['audio'], refs[it['ref']].get('text', ''))
              if it.get('ref') in refs else None for it in chunk]
        kwargs = dict(text=[it['text'] for it in chunk],
                      language=[_language(it.get('language')) for it in chunk],
                      num_step=num_step)
        if all(p is not None for p in ps):
            kwargs['voice_clone_prompt'] = ps
        elif any(it.get('instruct') for it in chunk):
            kwargs['instruct'] = [it.get('instruct') for it in chunk]
        durations = [it.get('duration') for it in chunk]
        if any(d for d in durations):
            kwargs['duration'] = [float(d) if d else None for d in durations]
        wavs = [w.reshape(-1) for w in model.generate(**kwargs)]
        # Câu rất ngắn đôi khi bị cắt khoảng lặng xoá sạch -> rỗng: đọc lại không cắt, rồi ép độ dài
        for k, w in enumerate(wavs):
            if w.size >= model.sampling_rate * 0.2:
                continue
            single = dict(text=kwargs['text'][k], language=kwargs['language'][k], num_step=num_step)
            if 'voice_clone_prompt' in kwargs:
                single['voice_clone_prompt'] = kwargs['voice_clone_prompt'][k]
            if 'instruct' in kwargs:
                single['instruct'] = kwargs['instruct'][k]
            for extra in ({'postprocess_output': False},
                          {'postprocess_output': False, 'duration': max(1.0, 0.18 * len(single['text']))}):
                w = model.generate(**single, **extra)[0].reshape(-1)
                if w.size >= model.sampling_rate * 0.2:
                    break
            wavs[k] = w
        out.extend(wavs)
    return out


def _encode(wav) -> str:
    buf = io.BytesIO()
    sf.write(buf, wav, model.sampling_rate, format='FLAC', subtype='PCM_16')
    return base64.b64encode(buf.getvalue()).decode()


def _transcribe(audios: list, languages: list) -> list:
    with asr_lock:
        if model._asr_pipe is None:
            model.load_asr_model(ASR_MODEL)
    texts = [''] * len(audios)
    groups = {}
    for i, code in enumerate(languages):
        code = (code or '').lower()
        groups.setdefault(WHISPER_LANG.get(code, code.split('-')[0]) or None, []).append(i)
    for lang, idx in groups.items():
        inputs = [{'array': np.asarray(audios[i][0], dtype=np.float32)[:audios[i][1] * 30],
                   'sampling_rate': audios[i][1]} for i in idx]
        kwargs = {'task': 'transcribe'}
        if lang:
            kwargs['language'] = lang
        with asr_lock:
            res = model._asr_pipe(inputs, batch_size=16, generate_kwargs=kwargs)
        for i, r in zip(idx, res):
            texts[i] = (r.get('text') or '').strip()
    return texts


def handler(job):
    body = job.get('input') or {}
    items = body.get('items') or []
    if body.get('op') == 'health':
        return {'ok': True}
    if not items or len(items) > 64:
        return {'error': 'items phải có 1-64 câu'}
    started = time.time()
    if body.get('op') == 'asr':
        audios = []
        for it in items:
            wav, sr = sf.read(io.BytesIO(base64.b64decode(it['audio'])), dtype='float32', always_2d=True)
            audios.append((wav.mean(axis=1), sr))
        texts = _transcribe(audios, [it.get('language') for it in items])
        return {'texts': texts, 'seconds': round(time.time() - started, 2)}
    wavs = _synthesize(body.get('refs') or {}, items, int(body.get('num_step', 32)))
    out = {'audios': [_encode(w) for w in wavs]}
    if body.get('asr'):
        sr = model.sampling_rate
        out['heard'] = _transcribe([(w, sr) for w in wavs], [it.get('language') for it in items])
    out['seconds'] = round(time.time() - started, 2)
    return out


if __name__ == '__main__':
    import runpod
    runpod.serverless.start({'handler': handler})
