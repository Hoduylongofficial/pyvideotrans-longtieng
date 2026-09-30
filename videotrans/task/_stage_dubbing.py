import copy
import re
import shutil
import time
from pathlib import Path

from videotrans.configure._paths import DUBBING_CACHE
from videotrans.configure.config import tr, app_cfg, settings, logger
from videotrans.configure.excepts import DubbingSrtError
from videotrans.tts import run as run_tts, SUPPORT_CLONE, OMNIVOICE_TTS
from videotrans.util.help_misc import get_md5, vail_file
from videotrans.util.help_srt import get_subtitle_from_srt, delete_punc


class DubbingMixin:

    def dubbing(self) -> None:
        _st=time.time()
        if self._exit() or self.cfg.app_mode == 'tiqu':
            return
        if self.should_dubbing:
            self.signal(text=tr('kaishipeiyin'))
        self.precent += 3
        self._tts()
        
        if  Path(self.cfg.source_sub).exists():
            logger.debug('配音结束后，移除原始字幕中所有标点')
            subs = get_subtitle_from_srt(self.cfg.source_sub)
            for it in subs:
                if self.cfg.fix_punc==2:
                    it['text']=delete_punc(it['text'])
                it['text']=it['text'].strip('...')
            self._save_srt_target(subs, self.cfg.source_sub)
        if self.should_dubbing:
            self.signal(text=tr('The dubbing is finished'))
            logger.debug(f'[语音合成阶段结束耗时]:{time.time()-_st}s')

    def _tts(self) -> None:
        if not self.should_dubbing:
            self.signal(text='Skip tts')
            return
        queue_tts = []
        subs = get_subtitle_from_srt(self.cfg.target_sub)
        source_subs = get_subtitle_from_srt(self.cfg.source_sub)
        if len(subs) < 1:
            raise DubbingSrtError(f"SRT file error:{self.cfg.target_sub}")
        try:
            rate = int(str(self.cfg.voice_rate).replace('%', ''))
        except (ValueError,TypeError):
            rate = 0

        rate = f"+{rate}%" if rate >= 0 else f"{rate}%"

        line_roles = app_cfg.line_roles
        voice_role = self.cfg.voice_role
        logger.debug(f'{line_roles=}')
        # 缓存键要能区分“声音来源”：OmniVoice 远程固定参考音色 -> 参考音频内容；
        # clone 逐句克隆 -> 源视频 + 原句时间。否则换了参考音色或换了视频仍会命中旧配音
        fixed_voice = ''
        if self.cfg.tts_type == OMNIVOICE_TTS:
            from videotrans.tts._omnivoice_modal import remote_configured, fixed_ref, native_voice, NATIVE_INSTRUCT, NATIVE_DIR
            ref = fixed_ref() if remote_configured() else None
            if remote_configured() and native_voice():
                # giọng mẫu bản xứ của ngôn ngữ này: khoá theo nội dung file mẫu (tạo lại mẫu -> đọc lại)
                import hashlib
                nref = NATIVE_DIR / f'{self.cfg.target_language_code}.wav'
                fixed_voice = 'native:' + (hashlib.md5(nref.read_bytes()).hexdigest() if nref.is_file() else NATIVE_INSTRUCT)
            elif ref:
                import hashlib
                fixed_voice = 'fixed:' + hashlib.md5(Path(ref[0]).read_bytes() + ref[1].encode()).hexdigest()
        for i, it in enumerate(subs):
            if it['end_time'] < it['start_time'] or not it['text'].strip():
                continue
            voice = line_roles.get(f'{it["line"]}', voice_role) if line_roles else voice_role
            voice_key = voice
            if fixed_voice:
                voice_key = fixed_voice
            elif str(voice).strip().lower() == 'clone' and source_subs and i < len(source_subs):
                voice_key = f"clone:{self.cfg.name}:{source_subs[i]['start_time']}-{source_subs[i]['end_time']}"

            _key = get_md5(f"{self.cfg.target_language_code}-{it['text']}-{voice_key}-{rate}-{self.cfg.volume}-{self.cfg.pitch}-{self.cfg.tts_type}")

            tmp_dict = {
                "text": it['text'],
                "line": it['line'],
                "start_time": it['start_time'],
                "end_time": it['end_time'],
                "startraw": it['startraw'],
                "endraw": it['endraw'],
                "ref_text": source_subs[i]['text'] if source_subs and i < len(source_subs) else '',
                "start_time_source": source_subs[i]['start_time'] if source_subs and i < len(source_subs) else it[
                    'start_time'],
                "end_time_source": source_subs[i]['end_time'] if source_subs and i < len(source_subs) else it[
                    'end_time'],
                "role": voice,
                "rate": rate,
                "volume": self.cfg.volume,
                "pitch": self.cfg.pitch,
                "tts_type": self.cfg.tts_type,
                "filename": f"{self.cfg.cache_folder}/{i}-{_key}.wav"
            }
            _dubbing_cache=f'{DUBBING_CACHE}/{_key}.wav'
            if vail_file(_dubbing_cache):
                # 直接使用缓存
                shutil.copy2(_dubbing_cache,tmp_dict['filename'])
            if str(voice).strip().lower() == 'clone' and self.cfg.tts_type in SUPPORT_CLONE:
                tmp_dict['ref_wav'] = f"{self.cfg.cache_folder}/clone-{i}.wav"
                tmp_dict['ref_language'] = self.cfg.detect_language[:2]
            queue_tts.append(tmp_dict)

        self.queue_tts = copy.deepcopy(queue_tts)

        if not self.queue_tts or len(self.queue_tts) < 1:
            raise RuntimeError(f'字幕长度为0，无法继续配音')

        if len([it.get("ref_wav") for it in self.queue_tts if it.get("ref_wav")]) > 0:
            self._create_ref_from_vocal()

        run_tts(
            queue_tts=self.queue_tts,
            language=self.cfg.target_language_code,
            uuid=self.uuid,
            tts_type=self.cfg.tts_type,
            is_cuda=self.cfg.is_cuda
        )
        outname=None
        if settings.get('save_segment_audio', False):
            outname = self.cfg.target_dir + f'/segment_audio_{self.cfg.noextname}'
            Path(outname).mkdir(parents=True, exist_ok=True)
        for it in self.queue_tts:
            it['text']=it['text'].strip('...')
            if self.cfg.fix_punc==2:
                it['text']=delete_punc(it['text'])
            if Path(it['filename']).exists():
                # 保存缓存
                shutil.copy2(it['filename'],f'{DUBBING_CACHE}/'+Path(it['filename']).name.split('-')[-1])
                if outname:
                    text = re.sub(r'["\'*?\\/|:<>\r\n\t]+', '', it['text'], flags=re.I | re.S)
                    name = f'{outname}/{it["line"]}-{text[:60]}.wav'
                    shutil.copy2(it['filename'], name)
        
