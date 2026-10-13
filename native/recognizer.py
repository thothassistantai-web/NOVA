"""Cancelable clients for a persistent, serialized speech-recognition worker."""
import atexit,json,os,select,subprocess,threading,time,uuid
from pathlib import Path
from PyQt5.QtCore import QThread
from behavior_log import event
_LOCK=threading.Lock();_WORKER=None;_CONFIG=None;_LOG=None

def read_reply(process,timeout,cancel=lambda:False):
    started=time.monotonic()
    while time.monotonic()-started<timeout:
        if cancel():return None
        if process.poll() is not None:raise RuntimeError('Speech-recognition worker exited; retry the turn.')
        buffered=getattr(process,'_nova_rx',b'')
        if b'\n' in buffered:
            line,process._nova_rx=buffered.split(b'\n',1)
            return json.loads(line)
        ready,_,_=select.select([process.stdout],[],[],.1)
        if ready:process._nova_rx=buffered+os.read(process.stdout.fileno(),4096)
    raise TimeoutError('Speech recognition timed out.')

def ensure(config):
    global _WORKER,_CONFIG,_LOG
    signature=(config['whisper_python'],config['whisper_model'])
    if _WORKER and _WORKER.poll() is None and _CONFIG==signature:return _WORKER
    shutdown()
    _LOG=open(Path.home()/'.nova/logs/recognizer.log','a');_CONFIG=signature
    _WORKER=subprocess.Popen([signature[0],'-u',str(Path(__file__).with_name('recognizer_worker.py')),signature[1]],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=_LOG,bufsize=0,env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'})
    result=read_reply(_WORKER,90)
    if not result or not result.get('ready'):raise RuntimeError('Recognition worker did not become ready.')
    event('recognizer_ready',load_seconds=round(result['load_seconds'],3))
    return _WORKER

def transcribe(config,path,cancel=lambda:False):
    while not _LOCK.acquire(timeout=.1):
        if cancel():return None
    try:
        if cancel():return None
        process=ensure(config);request_id=str(uuid.uuid4())
        process.stdin.write((json.dumps({'id':request_id,'path':path})+'\n').encode());process.stdin.flush()
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            reply=read_reply(process,max(1,deadline-time.monotonic()),cancel)
            if reply is None:return None
            if reply.get('id')!=request_id:continue
            if reply.get('error'):raise RuntimeError(reply['error'])
            event('recognition_inference',seconds=round(reply['seconds'],3),worker_pid=process.pid)
            return reply['text']
        raise TimeoutError('Speech recognition timed out.')
    except TimeoutError:
        shutdown();raise
    finally:_LOCK.release()

def shutdown():
    global _WORKER,_LOG
    if _WORKER:
        if _WORKER.poll() is None:
            _WORKER.terminate()
            try:_WORKER.wait(timeout=3)
            except subprocess.TimeoutExpired:_WORKER.kill();_WORKER.wait(timeout=3)
        for stream in [_WORKER.stdin,_WORKER.stdout]:
            if stream:stream.close()
        _WORKER=None
    if _LOG:_LOG.close();_LOG=None
atexit.register(shutdown)

class RecognitionWarm(QThread):
    def __init__(self,config):super().__init__();self.config=config
    def run(self):
        try:
            with _LOCK:ensure(self.config)
        except Exception as e:event('recognizer_warm_failed',error=str(e))
