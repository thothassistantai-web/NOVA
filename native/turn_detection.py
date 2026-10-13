"""Local audio-native turn completion; fixed-time fallback remains bounded."""
import threading,time,os
from pathlib import Path
from PyQt5.QtCore import QThread
from behavior_log import event
_LOCK=threading.Lock();_SESSION=None;_FEATURES=None;_FAILED=False
MODEL=Path(__file__).resolve().parent.parent/'assets/turn-detection/smart-turn-v3.2-cpu.onnx'

def load():
    global _SESSION,_FEATURES,_FAILED
    with _LOCK:
        if _SESSION is not None:return True
        if _FAILED:return False
        try:
            import onnxruntime as ort
            os.environ['USE_TORCH']='0';os.environ['USE_TF']='0';os.environ['USE_FLAX']='0'
            from transformers import WhisperFeatureExtractor
            options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
            _SESSION=ort.InferenceSession(str(MODEL),sess_options=options,providers=['CPUExecutionProvider'])
            _FEATURES=WhisperFeatureExtractor(chunk_length=8)
            event('adaptive_turn_model_ready');return True
        except Exception as e:_FAILED=True;event('adaptive_turn_fallback',error=str(e));return False

def endpoint(pcm,silence):
    if silence>=3.5:return True
    if not load():return silence>=1.25
    import numpy as np
    started=time.monotonic()
    audio=np.frombuffer(pcm[-256000:],dtype=np.int16).astype(np.float32)/32768
    audio=np.pad(audio,(max(0,128000-len(audio)),0))
    with _LOCK:
        features=_FEATURES(audio,sampling_rate=16000,return_tensors='np',padding='max_length',max_length=128000,truncation=True,do_normalize=True).input_features.astype(np.float32)
        probability=float(_SESSION.run(None,{_SESSION.get_inputs()[0].name:features})[0].reshape(-1)[0])
    event('turn_completion_prediction',probability=round(probability,3),silence_seconds=round(silence,2),inference_seconds=round(time.monotonic()-started,3))
    return probability>=.65

class TurnWarm(QThread):
    def run(self):load()
