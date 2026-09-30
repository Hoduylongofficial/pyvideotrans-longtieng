# -*- coding: utf-8 -*-
"""
OmniVoice TTS chạy trên GPU thuê của Modal (modal.com), gọi qua HTTP.

Deploy (chỉ máy quản trị, 1 lần / mỗi khi sửa file này):
    uvx --from modal modal deploy modal_tts/omnivoice_modal.py

Cần sẵn Secret "omnivoice-auth" chứa OMNIVOICE_API_KEY (DOI_TTS.bat mục 5 tự tạo).
Máy nhân viên KHÔNG cần cài modal: chỉ cần URL + key (DOI_TTS.bat mục 2).

API: POST <url>/tts   header  Authorization: Bearer <key>
  {"refs": {"r1": {"audio": "<base64 wav/flac>", "text": "..."}},
   "items": [{"text": "...", "ref": "r1", "language": "ro", "duration": 2.5,
              "instruct": "male, middle-aged"}],   # instruct: chỉ dùng khi không có ref
   "num_step": 32}
  -> {"audios": ["<base64 flac 24kHz>", ...], "seconds": 1.23}
  Giọng mẫu gửi 1 lần trong "refs", nhiều câu dùng chung (clone từng câu thì mỗi câu 1 ref).
  refs.text rỗng -> server tự nhận dạng lời bằng Whisper (lần đầu chậm hơn).
  duration (giây, tuỳ chọn) -> ép câu đọc vừa khung thời gian phụ đề.
GET <url>/health -> {"ok": true}
"""
import modal

APP_NAME = 'omnivoice-tts'
MODEL_DIR = '/models/OmniVoice'
GPU = 'L4'            # ~0.80 USD/giờ, chỉ tính lúc đang chạy
BATCH = 16            # số câu đọc cùng lúc trên GPU
# Mã pyvideotrans không trùng mã OmniVoice: ar -> tiếng Ả Rập chuẩn (bản dịch ra tiếng chuẩn)
LANG_ALIASES = {'ar': 'arb'}

app = modal.App(APP_NAME)


def _download_model():
    from huggingface_hub import snapshot_download
    snapshot_download('k2-fsa/OmniVoice', local_dir=MODEL_DIR)
    # Whisper cho trường hợp giọng mẫu không kèm lời (OmniVoice tự nghe ra lời) — để sẵn trong image
    snapshot_download('openai/whisper-large-v3-turbo', allow_patterns=['*.json', '*.safetensors', '*.txt'])


image = (
    modal.Image.debian_slim(python_version='3.11')
    .apt_install('ffmpeg')
    .pip_install('omnivoice==0.2.0', 'fastapi[standard]', 'huggingface_hub', 'soundfile')
    .run_function(_download_model)   # model nằm sẵn trong image: container khởi động nhanh
)


@app.cls(gpu=GPU, image=image, timeout=900,
         # Rảnh 30 giây thì tắt. dub_all tạo giọng một mạch rồi mới render nên máy nào xong việc là
         # thừa; để 120s thì 8 máy x 2 phút chạy không ~ 16 phút GPU mỗi video (~12% tiền).
         scaledown_window=30,
         max_containers=8,          # chặn trần: tối đa 8 GPU cùng lúc (dub_all tạo giọng trước 8 luồng)
         secrets=[modal.Secret.from_name('omnivoice-auth')])
class OmniVoiceTTS:
    @modal.enter()
    def load(self):
        import torch
        from omnivoice import OmniVoice
        self.model = OmniVoice.from_pretrained(MODEL_DIR, device_map='cuda:0', dtype=torch.float16)
        self.prompts = {}   # cache giọng mẫu: cùng 1 file mẫu thì chỉ mã hoá 1 lần

    def _prompt(self, ref_b64: str, ref_text: str):
        import base64, hashlib, io
        import soundfile as sf
        import torch
        key = hashlib.sha1((ref_b64 + '|' + (ref_text or '')).encode()).hexdigest()
        if key not in self.prompts:
            wav, sr = sf.read(io.BytesIO(base64.b64decode(ref_b64)), dtype='float32', always_2d=True)
            self.prompts[key] = self.model.create_voice_clone_prompt(
                (torch.from_numpy(wav.T.copy()), sr), ref_text=ref_text or None)
            if len(self.prompts) > 512:
                self.prompts.pop(next(iter(self.prompts)))
        return self.prompts[key]

    def _language(self, code):
        # Mã của pyvideotrans (zh-tw, pt-br...) -> mã OmniVoice; không nhận ra thì để model tự đoán
        if not code:
            return None
        ids = self.model.supported_language_ids()
        code = LANG_ALIASES.get(code.lower(), code)
        for c in (code, code.lower(), code.split('-')[0].lower()):
            if c in ids:
                return c
        return None

    def _synthesize(self, refs: dict, items: list, num_step: int) -> list:
        import base64, io
        import soundfile as sf
        out = []
        for i in range(0, len(items), BATCH):
            chunk = items[i:i + BATCH]
            prompts = [self._prompt(refs[it['ref']]['audio'], refs[it['ref']].get('text', ''))
                       if it.get('ref') in refs else None for it in chunk]
            kwargs = dict(text=[it['text'] for it in chunk],
                          language=[self._language(it.get('language')) for it in chunk],
                          num_step=num_step)
            if all(p is not None for p in prompts):
                kwargs['voice_clone_prompt'] = prompts
            elif any(it.get('instruct') for it in chunk):
                # Mô tả giọng (vd "male, middle-aged"): tạo giọng mẫu bản xứ cho ngôn ngữ mà giọng mẫu
                # tiếng Anh làm lơ lớ (ms, fil...)
                kwargs['instruct'] = [it.get('instruct') for it in chunk]
            durations = [it.get('duration') for it in chunk]
            if any(d for d in durations):
                kwargs['duration'] = [float(d) if d else None for d in durations]
            wavs = [w.reshape(-1) for w in self.model.generate(**kwargs)]
            # Câu rất ngắn ("並沒有。", "แอปเดียว") đôi khi bị bước cắt khoảng lặng xoá sạch -> rỗng.
            # Đọc lại từng câu: lần 2 không cắt khoảng lặng, lần 3 ép độ dài tối thiểu.
            for k, w in enumerate(wavs):
                if w.size >= self.model.sampling_rate * 0.2:
                    continue
                single = dict(text=kwargs['text'][k], language=kwargs['language'][k], num_step=num_step)
                if 'voice_clone_prompt' in kwargs:
                    single['voice_clone_prompt'] = kwargs['voice_clone_prompt'][k]
                if 'instruct' in kwargs:
                    single['instruct'] = kwargs['instruct'][k]
                for extra in ({'postprocess_output': False},
                              {'postprocess_output': False, 'duration': max(1.0, 0.18 * len(single['text']))}):
                    w = self.model.generate(**single, **extra)[0].reshape(-1)
                    if w.size >= self.model.sampling_rate * 0.2:
                        break
                wavs[k] = w
            for wav in wavs:
                buf = io.BytesIO()
                sf.write(buf, wav, self.model.sampling_rate, format='FLAC', subtype='PCM_16')
                out.append(base64.b64encode(buf.getvalue()).decode())
        return out

    @modal.asgi_app()
    def web(self):
        import hmac, os, time
        from fastapi import FastAPI, Header, HTTPException

        api = FastAPI()
        expected = os.environ['OMNIVOICE_API_KEY']

        @api.get('/health')
        def health():
            return {'ok': True}

        @api.post('/tts')
        def tts(body: dict, authorization: str = Header(default='')):
            if not hmac.compare_digest(authorization.removeprefix('Bearer ').strip(), expected):
                raise HTTPException(status_code=401, detail='sai key')
            items = body.get('items') or []
            if not items or len(items) > 64:
                raise HTTPException(status_code=400, detail='items phải có 1-64 câu')
            started = time.time()
            audios = self._synthesize(body.get('refs') or {}, items, int(body.get('num_step', 32)))
            return {'audios': audios, 'seconds': round(time.time() - started, 2)}

        return api
