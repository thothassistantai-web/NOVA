"""Cached local neural speech synthesis and interruptible playback."""
import json,os,re,subprocess,tempfile,threading,time,wave
from pathlib import Path
from PyQt5.QtCore import QThread,pyqtSignal
from behavior_log import event
_CACHE={};_LOCK=threading.RLock()

def load_voice(model):
    with _LOCK:
        if model not in _CACHE:
            import onnxruntime
            from piper import PiperVoice
            from piper.config import PiperConfig
            started=time.monotonic();options=onnxruntime.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            _CACHE[model]=PiperVoice(config=PiperConfig.from_dict(json.loads(Path(model+'.json').read_text())),session=onnxruntime.InferenceSession(model,sess_options=options,providers=['CPUExecutionProvider']))
            event('voice_model_loaded',voice=model,load_seconds=round(time.monotonic()-started,3))
        return _CACHE[model]

def generate_wav(text,path,config,cancel):
    from cloud_speech import synthesize
    if synthesize(text,path,config,cancel):return
    if cancel():return
    with _LOCK:
        voice=load_voice(config['tts_model'])
        if cancel():return
        from piper.config import SynthesisConfig
        with wave.open(path,'wb') as output:voice.synthesize_wav(text,output,SynthesisConfig(volume=1.0))
        from audio_quality import limit_wav
        limit_wav(path,config.get('tts_volume_percent',175)/100.0)

class VoiceWarm(QThread):
    def __init__(self,config):super().__init__();self.config=config
    def cancel(self):pass
    def run(self):
        try:
            import os
            load_voice(self.config['tts_model'])
        except Exception as e:
            event('voice_warm_failed',error=str(e))
        finally:
            pass

class Speech(QThread):
    playback_started=pyqtSignal();error=pyqtSignal(str)
    def __init__(self,text,config):
        super().__init__();self.text=text;self.config=dict(config);self.cancelled=threading.Event();self.process=None
    def cancel(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:self.process.terminate()
    def run(self):
        fd,path=tempfile.mkstemp(prefix='nova-neural-',suffix='.wav');os.close(fd);started=time.monotonic()
        event('tts_started',voice=self.config['tts_model'],text=self.text,volume_percent=self.config.get('tts_volume_percent',175))
        try:
            text=re.sub(r'```.*?```','Code details are in the chat.',self.text,flags=re.S)
            text=re.sub(r'[*#`]+','',text)
            generate_wav(text,path,self.config,self.cancelled.is_set)
            if self.cancelled.is_set():return
            event('tts_ready',synthesis_seconds=round(time.monotonic()-started,3))
            from audio_route import playback_command
            self.process=subprocess.Popen(playback_command(path,self.config.get('aec_sink')),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if hasattr(self,'partial_text'):self.partial_text=self.text
            self.playback_started.emit();self.process.wait(timeout=180)
            if self.process.returncode and not self.cancelled.is_set():raise RuntimeError('Speech playback failed; check the output device.')
            event('tts_completed',cancelled=self.cancelled.is_set(),duration_seconds=round(time.monotonic()-started,3))
        except Exception as e:
            if self.process and self.process.poll() is None:self.process.terminate()
            if not self.cancelled.is_set():event('tts_failed',error=str(e));self.error.emit(str(e))
        finally:Path(path).unlink(missing_ok=True)

class SentenceBuffer:
    """Only release stable sentence/phrase boundaries; retain incomplete words."""
    def __init__(self):self.text=''
    def feed(self,text,final=False):
        self.text+=text;result=[]
        while True:
            match=next((m for m in re.finditer(r'[.!?](?:\s+|$)|\n',self.text) if len(self.text[:m.end()].strip())>=16),None)
            if match and len(self.text[:match.end()].strip())>=16:
                result.append(self.text[:match.end()].strip());self.text=self.text[match.end():];continue
            if len(self.text)>220:
                cut=self.text.rfind(' ',0,200)
                if cut>60:result.append(self.text[:cut]);self.text=self.text[cut+1:];continue
            break
        if final and self.text.strip():result.append(self.text.strip());self.text=''
        return result

class StreamSpeech(Speech):
    """Collect a complete reply before generating one uninterrupted audio file."""
    def __init__(self,config):
        super().__init__('',config)
        import queue
        self.queue=queue.Queue();self.spoken_text='';self.partial_text='';self.input_done=False
    def add_text(self,text):
        if not self.cancelled.is_set():self.queue.put(text)
    def finish_input(self):self.input_done=True;self.queue.put(None)
    def heard_text(self):
        return (self.spoken_text+(' [interrupted during: '+self.partial_text+']' if self.partial_text else '')).strip()
    def run(self):
        import queue
        parts=[];started=time.monotonic()
        event('buffered_tts_started',volume_percent=self.config.get('tts_volume_percent',175))
        while not self.cancelled.is_set():
            try:part=self.queue.get(timeout=.1)
            except queue.Empty:continue
            if part is None:break
            parts.append(part)
        if self.cancelled.is_set():return
        self.text=''.join(parts).strip()
        if not self.text:return
        Speech.run(self)
        if not self.cancelled.is_set() and self.process and self.process.returncode==0:
            self.spoken_text=self.text;self.partial_text=''
        event('buffered_tts_completed',cancelled=self.cancelled.is_set(),duration_seconds=round(time.monotonic()-started,3),heard=self.heard_text())
