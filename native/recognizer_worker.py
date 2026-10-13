"""Private line-based worker; one Whisper model remains loaded across utterances."""
import json,sys,wave,time
import numpy as np
from faster_whisper import WhisperModel
start=time.monotonic()
model=WhisperModel(sys.argv[1],device='cpu',compute_type='int8',cpu_threads=2)
print(json.dumps({'ready':True,'load_seconds':time.monotonic()-start}),flush=True)
for line in sys.stdin:
    request=json.loads(line)
    try:
        with wave.open(request['path']) as w:
            if w.getframerate()!=16000 or w.getnchannels()!=1 or w.getsampwidth()!=2:raise ValueError('Expected 16 kHz mono PCM')
            audio=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).astype(np.float32)/32768
        start=time.monotonic()
        segments,_=model.transcribe(audio,beam_size=1,language='en',condition_on_previous_text=False,without_timestamps=True,max_new_tokens=256)
        text=' '.join(x.text.strip() for x in segments).strip()
        print(json.dumps({'id':request['id'],'text':text,'seconds':time.monotonic()-start}),flush=True)
    except Exception as e:print(json.dumps({'id':request.get('id'),'error':str(e)}),flush=True)
