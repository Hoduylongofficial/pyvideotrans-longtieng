import re
from dataclasses import dataclass

from videotrans.configure.config import params
from videotrans.translator._openaicompat import OpenAICampat


def normalize_ninerouter_url(url: str) -> str:
    """9Router 的 OpenAI 兼容地址形如 https://<域名>/v1，用户可能漏写 /v1 或多写 /chat/completions"""
    url = str(url or '').strip().rstrip('/')
    if not url:
        return ''
    if not url.startswith('http'):
        url = 'https://' + url
    url = re.sub(r'/chat/completions$', '', url)
    if not re.search(r'/v\d+$', url):
        url += '/v1'
    return url


@dataclass
class NineRouter(OpenAICampat):

    def __post_init__(self):
        self.ainame = 'ninerouter'
        self.api_url = normalize_ninerouter_url(params.get('ninerouter_api', ''))
        self.api_key = params.get('ninerouter_key', '')
        self.model_name = params.get('ninerouter_model', '')
        # Tối thiểu 32768: bản dịch tự nhiên (không nén) + phần suy nghĩ của Gemini vượt 8192 với lô 50 câu
        # tiếng Thái / Đức (đo 10/2026) -> 9Router cắt cụt mà không báo finish_reason=length, phần mềm tưởng
        # AI bỏ sót 20-50 câu. Cả 4 model trên 9Router đều nhận 32768.
        self.max_tokens = max(32768, int(float(params.get('ninerouter_max_token', 8192) or 8192)))
        _reason = params.get('ninerouter_reasoning_effort')
        self.reasoning_effort = None if not _reason or _reason == 'No' else _reason
        super().__post_init__()
