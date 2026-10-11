# -*- coding: utf-8 -*-
"""
Server OmniVoice trên máy vast.ai Serverless (chạy bằng supervisor, xem vast_tts/provision.sh).

Dùng lại nguyên engine của RunPod (runpod_tts/handler.py, tải về /opt/omnivoice/handler.py): cùng model,
cùng cách đọc, cùng JSON. PyWorker (vast_tts/worker.py) nhận request từ máy khách, kiểm chữ ký của vast.ai
rồi chuyển "payload" sang đây:
  POST /tts  {"refs": {...}, "items": [...], "num_step": 32, "asr": false} -> {"audios": [...], "seconds": ...}
  POST /asr  {"items": [{"audio": "<base64>", "language": "de"}]}          -> {"texts": [...]}
  GET  /health
Chỉ nghe 127.0.0.1: ngoài máy chỉ gọi được qua PyWorker (có kiểm chữ ký).
"""
import asyncio
import sys

from aiohttp import web

sys.path.insert(0, '/opt/omnivoice')
PORT = 18000
READY = 'OMNIVOICE_READY'     # worker.py chờ dòng log này rồi mới chạy benchmark

print('OmniVoice: đang nạp model...', flush=True)
try:
    import handler  # noqa: E402 - nạp model lên GPU (~20 giây)
except Exception as e:  # noqa: BLE001 - báo PyWorker để vast.ai bỏ máy này, thuê máy khác
    print(f'OMNIVOICE_FATAL {type(e).__name__}: {e}', flush=True)
    raise

gpu = asyncio.Lock()          # GPU đọc từng lượt một (mỗi lượt đã gộp 16 câu)


async def run(request: web.Request, op: str) -> web.Response:
    body = await request.json()
    body['op'] = op
    async with gpu:
        out = await asyncio.get_running_loop().run_in_executor(None, handler.handler, {'input': body})
    return web.json_response(out, status=400 if set(out) == {'error'} else 200)


async def tts(request):
    return await run(request, 'tts')


async def asr(request):
    return await run(request, 'asr')


async def health(_request):
    return web.json_response({'ok': True})


async def announce(_app):
    print(READY, flush=True)


app = web.Application(client_max_size=64 * 1024 * 1024)
app.add_routes([web.post('/tts', tts), web.post('/asr', asr), web.get('/health', health)])
app.on_startup.append(announce)

if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=PORT, print=None)
