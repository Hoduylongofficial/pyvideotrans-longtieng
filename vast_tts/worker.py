# -*- coding: utf-8 -*-
"""
PyWorker của vast.ai Serverless cho OmniVoice (provision.sh chép file này vào /workspace/vast-pyworker).

vast.ai tự chạy file này sau khi provision.sh xong: nó nhận request của máy khách, kiểm chữ ký do
run.vast.ai/route cấp, rồi chuyển payload sang vast_tts/model_server.py (127.0.0.1:18000).
Tải công việc (workload) = số câu trong lượt: vast.ai dựa vào đó và benchmark để quyết định bật bao nhiêu máy.
"""
from vastai import BenchmarkConfig, HandlerConfig, LogActionConfig, Worker, WorkerConfig

BENCH_TEXTS = ['Welcome back to the channel, today we compare the best hosting providers.',
               'The price starts at two dollars and ninety nine cents per month.',
               'Here is what you get for that money.',
               'Let us look at the speed test results.']
# Benchmark không có giọng mẫu: OmniVoice tự tạo giọng theo mô tả (vài giây GPU)
BENCH = [{'items': [{'text': t, 'language': 'en', 'instruct': 'male, middle-aged'} for t in BENCH_TEXTS]}]


def workload(payload: dict) -> float:
    return float(len(payload.get('items') or [None]))


worker_config = WorkerConfig(
    model_server_url='http://127.0.0.1',
    model_server_port=18000,
    model_log_file='/var/log/portal/omnivoice.log',
    model_healthcheck_url='/health',
    handlers=[
        HandlerConfig(
            route='/tts',
            allow_parallel_requests=False,   # model_server đọc từng lượt; xếp hàng ở đây
            max_queue_time=600.0,
            workload_calculator=workload,
            benchmark_config=BenchmarkConfig(dataset=BENCH, runs=2),
        ),
        HandlerConfig(
            route='/asr',
            allow_parallel_requests=False,
            max_queue_time=600.0,
            workload_calculator=workload,
        ),
    ],
    log_action_config=LogActionConfig(
        on_load=['OMNIVOICE_READY'],
        on_error=['OMNIVOICE_FATAL', 'CUDA out of memory', 'ModuleNotFoundError'],
        on_info=['OmniVoice:'],
    ),
)

Worker(worker_config).run()
