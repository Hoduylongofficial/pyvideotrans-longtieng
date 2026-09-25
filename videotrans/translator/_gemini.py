import logging
import random
import re,httpx
from dataclasses import dataclass, field
from typing import List, Union
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_not_exception_type, before_log, after_log
from videotrans.configure.excepts import NO_RETRY_EXCEPT, TranslateSrtError, StopTask
from videotrans.configure.config import tr,settings,params,logger,ROOT_DIR
from videotrans.translator._base import BaseTrans
from google import genai
from google.genai import types,errors
from pathlib import Path
from videotrans.util.help_misc import get_prompt


@dataclass
class Gemini(BaseTrans):
    prompt: str = field(init=False)
    api_keys: List[str] = field(init=False, repr=False)  # Use repr=False for sensitive data

    def __post_init__(self):
        super().__post_init__()
        self.model_name = params.get("gemini_model",'gemini-3.5-flash')
        lang_prompt=''
        lang_prompt_file=f'{ROOT_DIR}/videotrans/prompts/language_prompts/{self.target_language_name}.txt'
        if Path(lang_prompt_file).exists():
            lang_prompt=Path(lang_prompt_file).read_text(encoding='utf-8')
        self.prompt = get_prompt(ainame='gemini',aisendsrt=self.aisendsrt).replace('{lang}', self.target_language_name).replace('{lang_prompt}',lang_prompt)
        self.api_keys = [k.strip() for k in params.get('gemini_key', '').split(',') if k.strip()] or ['']
        # 随机起点，多个进程并行翻译时不会都挤在第一个 key 上
        start = random.randrange(len(self.api_keys))
        self.api_keys = self.api_keys[start:] + self.api_keys[:start]


    @retry(retry=retry_if_not_exception_type(NO_RETRY_EXCEPT), stop=(stop_after_attempt(settings.get('retry_nums'))), wait=wait_fixed(2), before=before_log(logger, logging.INFO),after=after_log(logger, logging.INFO))
    def _item_task(self, data: Union[List[str], str]) -> str:
        if self._exit(): return
        text = "\n".join([i.strip() for i in data]) if isinstance(data, list) else data
        try:
            # 多个 key 时：某个 key 被限流/失效，换下一个 key 重试本批，全部失败才报错
            for n in range(len(self.api_keys)):
                api_key = self.api_keys.pop(0)
                self.api_keys.append(api_key)
                try:
                    return self._send(api_key, text)
                except errors.APIError as e:
                    bad_key = e.code in (401, 403, 429) or (e.code == 400 and 'API key' in str(e.message))
                    if n == len(self.api_keys) - 1 or not bad_key:
                        raise
                    logger.warning(f'[Gemini] key ...{api_key[-4:]} 返回 {e.code}，换下一个 key')
        except httpx.ConnectTimeout as e:
            raise StopTask(f' {tr("Unable to connect to remote API","Gemini AI")}\n{e}') from e
        except errors.APIError as e:
            logger.warning(f'{e=}')
            if e.code in [400,403,404,429,500]:
                raise StopTask(e.message)
            raise TranslateSrtError(e.message)

    def _send(self, api_key: str, text: str) -> str:
        client = genai.Client(
            api_key=api_key,
            http_options = types.HttpOptions(
                client_args={'proxy': self.proxy_str},
                async_client_args={'proxy': self.proxy_str},
            )

        )
        model = params.get("gemini_model","gemini-2.5-flash")
        message=self.prompt.replace('{batch_input}', f'{text}')
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=message),
                ],
            ),
        ]
        think_cfg=types.ThinkingConfig(
                    thinking_level="HIGH",
            )
        if model.lower().startswith('gemini-2'):
            think_cfg=types.ThinkingConfig(
                    thinking_budget=24576,
                )
            
        generate_content_config = types.GenerateContentConfig(
            temperature=float(settings.get('aitrans_temperature',0.1)),
            max_output_tokens=int(params.get("gemini_maxtoken",65530)),
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                )
              ],

            thinking_config = think_cfg,
            system_instruction=[
                types.Part.from_text(text='You are a top-tier Subtitle Translation Engine.'),
            ],
        )
        if model.startswith('gemini-1.') or model.startswith('gemini-2.0'):            
            generate_content_config = types.GenerateContentConfig()

        result = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            result+=chunk.text if chunk.text else ""
                 
        logger.debug(f'{result=}')
        if not result:
            logger.warning(f'[gemini]请求失败')
            raise TranslateSrtError(f"[Gemini]result is empty")
            
        match = re.search(r'<TRANSLATE_TEXT>(.*?)(?:</TRANSLATE_TEXT>|$)',
                          re.sub(r'<think>(.*?)</think>', '', result, flags=re.I | re.S), re.S | re.I)
        if match:
            return match.group(1)
        raise TranslateSrtError(f"Gemini result is emtpy")
