
from dataclasses import dataclass
from videotrans.configure.config import params
from videotrans.translator._openaicompat import OpenAICampat

@dataclass
class OpenRouter(OpenAICampat):

    def __post_init__(self):
        self.ainame ='openrouter'
        # 界面保存的键名是 openrouter_max_token，此前误读为复数导致设置始终不生效
        self.max_tokens =int(float(params.get('openrouter_max_token',8192)))
        self.model_name = params.get('openrouter_model', "")
        self.api_url = 'https://openrouter.ai/api/v1'
        self.api_key = params.get('openrouter_key', '')
        _reason=params.get('openrouter_reasoning_effort')
        self.reasoning_effort=None if not _reason or _reason=='No' else _reason
        
        super().__post_init__()

