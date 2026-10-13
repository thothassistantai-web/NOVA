"""Bounded PCM capture, pre-roll, adaptive endpointing and speech-onset signals."""
import array,math,os,select,signal,subprocess,tempfile,threading,time,wave,sys
from pathlib import Path
from PyQt5.QtCore import QThread,pyqtSignal
from audio_route import capture_command
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
import webrtcvad

class EndpointDetector:
    def __init__(self,threshold=450,silence_seconds=1.25,min_speech_seconds=.25,classifier=None):
        self.threshold=threshold;self.silence_seconds=silence_seconds;self.minimum=min_speech_seconds
        self.speech=0.;self.silence=0.;self.onset_gap=0.;self.buffer=b'';self.last_voiced=False
        self.classifier=classifier or webrtcvad.Vad(2).is_speech
    def feed(self,pcm):
        self.buffer+=pcm;packet_voiced=False
        while len(self.buffer)>=640:
            frame,self.buffer=self.buffer[:640],self.buffer[640:]
            samples=array.array('h');samples.frombytes(frame)
            rms=math.sqrt(sum(x*x for x in samples)/len(samples))
            voiced=rms>=self.threshold and self.classifier(frame,16000);packet_voiced|=voiced
            if voiced:self.speech+=.02;self.silence=0.;self.onset_gap=0.
            elif self.speech>=self.minimum:self.silence+=.02
            else:
                self.onset_gap+=.02
                if self.onset_gap>=.1:self.speech=0.
        self.last_voiced=packet_voiced
        return self.speech>=self.minimum and self.silence>=self.silence_seconds

class Capture(QThread):
    level=pyqtSignal(float);idle=pyqtSignal();ready=pyqtSignal();speech_onset=pyqtSignal();partial=pyqtSignal(str);result=pyqtSignal(str);error=pyqtSignal(str)
    def __init__(self,auto_send=False,threshold=450,silence_seconds=1.25,idle_timeout=8,source=None,monitor=False,endpoint=None):
        super().__init__();self.auto_send=auto_send;self.idle_timeout=idle_timeout;self.source=source;self.monitor=monitor;self.endpoint=endpoint
        self.detector=EndpointDetector(threshold,silence_seconds,min_speech_seconds=.35 if monitor else .25)
        self.cancelled=threading.Event();self.finished_input=threading.Event();self.process=None
        fd,self.path=tempfile.mkstemp(prefix='nova-voice-',suffix='.wav');os.close(fd)
    def cancel(self):self.cancelled.set()
    def finish(self):self.finished_input.set()
    @staticmethod
    def snapshot(audio):
        fd,path=tempfile.mkstemp(prefix='nova-partial-',suffix='.wav');os.close(fd)
        with wave.open(path,'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(audio)
        return path
    def run(self):
        error=None;idle=False;audio=bytearray();preroll=bytearray();heard=False;first=True;pending=b'';last_partial=0.;last_prediction=0.;speech_start=None
        try:
            self.process=subprocess.Popen(capture_command(self.source),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            started=time.monotonic()
            while not self.cancelled.is_set() and not self.finished_input.is_set():
                now=time.monotonic();elapsed=now-started
                if heard and now-speech_start>45:break
                if self.idle_timeout and elapsed>self.idle_timeout and not heard:idle=True;break
                if self.process.poll() is not None:raise RuntimeError('Microphone unavailable. Check your input device.')
                readable,_,_=select.select([self.process.stdout],[],[],.1)
                if not readable:continue
                chunk=os.read(self.process.stdout.fileno(),3200)
                if not chunk:raise RuntimeError('Microphone stopped unexpectedly.')
                pending+=chunk;n=len(pending)//2*2;pcm,pending=pending[:n],pending[n:]
                if first:self.ready.emit();first=False
                samples=array.array('h');samples.frombytes(pcm)
                rms=math.sqrt(sum(x*x for x in samples)/max(1,len(samples)))
                self.level.emit(min(1.0,max(0.0,(rms-150)/2500)))
                completed=self.detector.feed(pcm)
                if not heard:
                    preroll.extend(pcm);preroll=preroll[-19200:]
                    if self.detector.speech>=self.detector.minimum:
                        heard=True;speech_start=now;audio.extend(preroll);self.speech_onset.emit()
                else:audio.extend(pcm)
                if not heard:continue
                if now-last_partial>5 and len(audio)>48000:
                    last_partial=now;self.partial.emit(self.snapshot(bytes(audio)))
                if self.endpoint and self.detector.silence>=.55 and now-last_prediction>.35:
                    last_prediction=now
                    if self.endpoint(bytes(audio),self.detector.silence):break
                elif not self.endpoint and completed:break
            if self.finished_input.is_set() and not heard:idle=True
            if not idle and not self.cancelled.is_set() and not heard:raise RuntimeError("I didn't hear speech. Try again.")
            if heard and not self.cancelled.is_set():
                with wave.open(self.path,'wb') as output:
                    output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(audio)
        except Exception as e:error=str(e)
        finally:
            if self.process:
                if self.process.poll() is None:
                    self.process.send_signal(signal.SIGINT)
                    try:self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=2)
                if self.process.stdout:self.process.stdout.close()
        if self.cancelled.is_set() or error or idle:Path(self.path).unlink(missing_ok=True)
        if self.cancelled.is_set():return
        if idle:self.idle.emit()
        elif error:self.error.emit(error)
        else:self.result.emit(self.path)
