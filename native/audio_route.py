"""App-owned monitor-based echo cancellation; speech bypasses the EC playback node."""
import atexit,json,subprocess,time
from behavior_log import event
SOURCE='nova_clean_monitor';_HELPER=None

def nodes(kind):
    r=subprocess.run(['pactl','list','short',kind],capture_output=True,text=True,timeout=5,check=True)
    return {line.split('\t')[1] for line in r.stdout.splitlines() if '\t' in line}

def shutdown():
    global _HELPER
    if _HELPER:
        _HELPER.terminate()
        try:_HELPER.wait(timeout=3)
        except subprocess.TimeoutExpired:_HELPER.kill();_HELPER.wait()
        if _HELPER.stdin:_HELPER.stdin.close()
        _HELPER=None
atexit.register(shutdown)

def ensure():
    global _HELPER
    try:
        source=subprocess.check_output(['pactl','get-default-source'],text=True,timeout=5).strip()
        sink=subprocess.check_output(['pactl','get-default-sink'],text=True,timeout=5).strip()
        settings=__import__('pathlib').Path.home()/'.nova/desktop.json'
        config=json.loads(settings.read_text()) if settings.exists() else {}
        if not config.get('echo_capture_enabled',False):
            event('physical_microphone_ready',source=source,reason='echo filter is silent');return source,sink
        if source==SOURCE:raise RuntimeError('Choose the physical microphone as default input.')
        if SOURCE not in nodes('sources'):
            args={'monitor.mode':True,'audio.rate':48000,'audio.channels':1,'node.latency':'1024/48000',
              'capture.props':{'node.name':'nova_capture_monitor','target.object':source,'node.async':True},
              'source.props':{'node.name':SOURCE,'node.async':True},
              'sink.props':{'node.name':'nova_reference_monitor','target.object':sink,'node.async':True}}
            _HELPER=subprocess.Popen(['pw-cli'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,text=True)
            _HELPER.stdin.write('load-module libpipewire-module-echo-cancel '+json.dumps(args)+'\n');_HELPER.stdin.flush()
            for _ in range(20):
                if SOURCE in nodes('sources'):break
                if _HELPER.poll() is not None:raise RuntimeError('Echo monitor helper exited.')
                time.sleep(.1)
        if SOURCE in nodes('sources'):
            event('echo_monitor_ready',source=SOURCE,physical_playback_sink=sink);return SOURCE,sink
    except Exception as error:event('echo_cancel_unavailable',error=str(error));shutdown()
    return None,None

def capture_command(source=None):
    if source:return ['parec','--device='+source,'--format=s16le','--rate=16000','--channels=1','--latency-msec=40']
    return ['arecord','-q','-f','S16_LE','-r','16000','-c','1','-t','raw']

def playback_command(path,sink=None,rate=None):
    return ['paplay','--latency-msec=100',*(['--device='+sink] if sink else []),str(path)]
