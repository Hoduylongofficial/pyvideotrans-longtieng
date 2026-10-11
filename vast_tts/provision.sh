#!/bin/bash
# OmniVoice TTS cho vast.ai Serverless — chạy 1 lần khi máy mới được thuê (biến PROVISIONING_SCRIPT của
# template trỏ tới file này trên GitHub). Máy dừng rồi bật lại (máy "lạnh") không chạy lại.
#  1. Cài OmniVoice vào /venv/main (torch có sẵn trong image vastai/pytorch)
#  2. Tải model k2-fsa/OmniVoice về /models/OmniVoice
#  3. Tải runpod_tts/handler.py (engine dùng chung với RunPod) + vast_tts/model_server.py, chạy bằng supervisor
#  4. Chép vast_tts/worker.py vào /workspace/vast-pyworker: script PyWorker của vast.ai thấy thư mục đã có
#     thì không clone repo nữa (repo này ~500 MB), cài requirements.txt rồi chạy worker.py
set -eo pipefail
RAW="https://raw.githubusercontent.com/Hoduylongofficial/pyvideotrans-longtieng/${OMNIVOICE_REF:-main}"

. /venv/main/bin/activate
apt-get update -qq && apt-get install -y -qq ffmpeg > /dev/null || echo "OmniVoice: không cài được ffmpeg (bỏ qua)"

# torchaudio phải cùng bản torch của image, không thì pip kéo torch mới (vài GB, có thể sai CUDA)
if ! python -c "import torchaudio" 2> /dev/null; then
    TV=$(python -c "import torch; print(torch.__version__.split('+')[0])")
    CU=$(python -c "import torch; print('cu' + torch.version.cuda.replace('.', ''))")
    pip install -q "torchaudio==${TV}" --index-url "https://download.pytorch.org/whl/${CU}"
fi
pip install -q omnivoice==0.2.0 huggingface_hub soundfile aiohttp
python -c "from huggingface_hub import snapshot_download as d; d('k2-fsa/OmniVoice', local_dir='/models/OmniVoice')"

mkdir -p /opt/omnivoice /workspace/vast-pyworker /var/log/portal
curl -fsSL "$RAW/runpod_tts/handler.py" -o /opt/omnivoice/handler.py
curl -fsSL "$RAW/vast_tts/model_server.py" -o /opt/omnivoice/model_server.py
curl -fsSL "$RAW/vast_tts/worker.py" -o /workspace/vast-pyworker/worker.py
curl -fsSL "$RAW/vast_tts/requirements.txt" -o /workspace/vast-pyworker/requirements.txt

# Log ghi đè mỗi lần chạy: worker.py đọc log từ đầu để chờ dòng OMNIVOICE_READY
cat > /etc/supervisor/conf.d/omnivoice.conf << 'EOF'
[program:omnivoice]
command=/bin/bash -c '. /venv/main/bin/activate && exec python -u /opt/omnivoice/model_server.py > /var/log/portal/omnivoice.log 2>&1'
autostart=true
autorestart=true
startsecs=0
stopasgroup=true
killasgroup=true
EOF
supervisorctl reread && supervisorctl update
echo "OmniVoice: cài đặt xong"
