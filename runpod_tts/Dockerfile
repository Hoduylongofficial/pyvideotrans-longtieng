# OmniVoice TTS cho RunPod Serverless (dự phòng khi Modal hết hạn mức) — xem runpod_tts/handler.py
# RunPod build từ GitHub: Dockerfile Path = runpod_tts/Dockerfile. Thư mục build có thể là gốc repo
# hoặc runpod_tts/, nên COPY ghi cả hai đường (đường nào không có thì bỏ qua).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 HF_HOME=/models/hf PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install omnivoice==0.2.0 runpod==1.7.9 huggingface_hub soundfile

# Model nằm sẵn trong image: máy bật lên là đọc được, không tải lại mỗi lần
RUN python -c "from huggingface_hub import snapshot_download as d; \
d('k2-fsa/OmniVoice', local_dir='/models/OmniVoice'); \
d('openai/whisper-large-v3-turbo', allow_patterns=['*.json', '*.safetensors', '*.txt'])"

WORKDIR /app
COPY handler.py* runpod_tts/handler.py* /app/
CMD ["python", "-u", "/app/handler.py"]
