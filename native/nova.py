#!/usr/bin/python3
"""NOVA native desktop overlay. No browser server or Cargo build required."""
import json, math, os, signal, subprocess, sys, tempfile, threading, uuid, time
from pathlib import Path
from model_routes import catalogs, credential, route_key, refresh_router, LABELS, managed_config
import requests
from voice_capture import Capture
from recognizer import RecognitionWarm
from cloud_speech import transcribe as cached_transcribe
from audio_route import ensure as ensure_audio_route,playback_command
from turn_detection import endpoint as adaptive_endpoint,TurnWarm
from speech_output import Speech,VoiceWarm,StreamSpeech
from behavior_log import event, runtime
from system_context import prompt as context_prompt,local_answer
from agent_backend import run_agent,chat_with_tools
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint, QSettings, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QColor, QPainter, QPen, QRadialGradient, QIcon, QPixmap
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QPlainTextEdit, QLineEdit, QCheckBox, QSystemTrayIcon, QMenu, QSlider, QGraphicsOpacityEffect)

BASE = Path(__file__).resolve().parent.parent
DATA = Path.home()/'.nova'
DATA.mkdir(exist_ok=True)
CONFIG = DATA/'desktop.json'
DEFAULT = {'ollama_url':'http://127.0.0.1:11434','ollama_model':'tinyllama:latest',
 'openclaw_command':str(Path.home()/'.local/bin/openclaw'),
 'whisper_python':str(Path.home()/'openclaw/cache/cdh-transcribe-venv/bin/python'),
 'partial_transcripts':False,'adaptive_turns':True,'voice_idle_timeout':0,'barge_in_enabled':True,'tts_volume_percent':175,'tts_python':str(BASE/'.tts-venv/bin/python'),'tts_model':str(BASE/'assets/voices/en_US-lessac-medium.onnx'),'voice_threshold':450,'voice_silence_seconds':1.25,'whisper_model':'tiny.en','openai_model':'gpt-4.1-mini','claude_model':'claude-sonnet-4-5'}
config = dict(DEFAULT)
if CONFIG.exists():
    config.update(json.loads(CONFIG.read_text()))
else:
    CONFIG.write_text(json.dumps(DEFAULT,indent=2)); CONFIG.chmod(0o600)

class Task(QThread):
    delta = pyqtSignal(str)
    result = pyqtSignal(str)
    error = pyqtSignal(str)
    def __init__(self, provider, messages, session, model=None):
        super().__init__(); self.provider=provider; self.messages=messages; self.session=session
        self.model=model; self.route=route_key(provider,model)
        self.turn_id=str(uuid.uuid4());self.tools_enabled=True;self.output_started=False;self.action_started=False
        self.cancelled=threading.Event(); self.process=None; self.response=None
    def cancel(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None: self.process.terminate()
        if self.response: self.response.close()
    def run(self):
        started=time.monotonic();question=self.messages[-1]['content']
        event('request_started',turn_id=self.turn_id,route=self.route,prompt=question,tools_enabled=self.tools_enabled)
        try:
            text=local_answer(question)
            messages=[{'role':'system','content':context_prompt()}]+self.messages
            if text:event('local_facts_answer',turn_id=self.turn_id)
            elif self.provider in ['OpenClaw','Codex Agent','Cursor Agent']:
                backend={'OpenClaw':'OpenClaw','Codex Agent':'Codex','Cursor Agent':'Cursor'}[self.provider]
                text=run_agent(self,backend,question,self.session)
            elif self.provider=='Ollama':
                model=self.model['model'] if self.model else config['ollama_model']
                text=chat_with_tools(self,config['ollama_url'].rstrip('/')+'/v1','ollama',model,messages,'ollama',self.tools_enabled)
            elif self.provider in LABELS or self.provider=='Managed Free Models':
                if not self.model:raise RuntimeError('Select a model before sending.')
                actual=self.model['provider'];url,key=credential(actual)
                text=chat_with_tools(self,url,key,self.model['model'],messages,actual,self.tools_enabled)
            else:
                key=os.environ.get('OPENAI_API_KEY' if self.provider=='OpenAI API' else 'ANTHROPIC_API_KEY')
                if not key:raise RuntimeError('API key is not configured in the launch environment.')
                if self.provider=='OpenAI API':
                    model=self.model['model'] if self.model else config['openai_model']
                    text=chat_with_tools(self,'https://api.openai.com/v1',key,model,messages,'openai',self.tools_enabled)
                else:
                    r=requests.post('https://api.anthropic.com/v1/messages',headers={'x-api-key':key,'anthropic-version':'2023-06-01'},
                      json={'model':self.model['model'] if self.model else config['claude_model'],'messages':self.messages,'system':context_prompt(),'max_tokens':512},timeout=(5,120))
                    r.raise_for_status();text=''.join(x.get('text','') for x in r.json()['content'])
            if not self.cancelled.is_set():
                event('request_completed',turn_id=self.turn_id,route=self.route,response=text,duration_seconds=round(time.monotonic()-started,3));self.result.emit(text)
        except Exception as e:
            if self.process and self.process.poll() is None:self.process.terminate()
            from resilience import retryable,model_fallback
            if config.get('model_fallbacks',True) and retryable(e,self):
                try:
                    text=model_fallback(self,messages,self.tools_enabled)
                    if not self.cancelled.is_set():
                        event('request_completed',turn_id=self.turn_id,route=self.route,response=text,fallback=True,duration_seconds=round(time.monotonic()-started,3));self.result.emit(text)
                    return
                except Exception as fallback_error:e=fallback_error
            if not self.cancelled.is_set():
                event('request_failed',turn_id=self.turn_id,route=self.route,error=str(e),duration_seconds=round(time.monotonic()-started,3));self.error.emit(str(e))
        finally:
            if self.cancelled.is_set():event('request_cancelled',turn_id=self.turn_id,route=self.route)
            if self.response:self.response.close()

class Transcribe(QThread):
    result=pyqtSignal(str); error=pyqtSignal(str)
    def __init__(self, path, auto_send=False, partial=False): super().__init__(); self.partial_request=partial;self.path=path; self.auto_send=auto_send; self.process=None; self.cancelled=False
    def cancel(self):
        self.cancelled=True
        if self.process and self.process.poll() is None: self.process.terminate()
    def run(self):
        started=time.monotonic()
        try:
            text=cached_transcribe(dict(config,partial_request=self.partial_request),self.path,lambda:self.cancelled)
            if self.cancelled or text is None:return
            if not text.strip():raise RuntimeError('No speech detected. Try again or type your message.')
            event('transcription_latency',seconds=round(time.monotonic()-started,3))
            self.result.emit(text)
        except Exception as e:
            if not self.cancelled:self.error.emit(str(e))
        finally:Path(self.path).unlink(missing_ok=True)

class VoiceControl(QPushButton):
    def __init__(self,kind):
        super().__init__('');self.level=0.0;self.kind=kind;self.tint='#e7e7ea'
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.setPen(Qt.NoPen);p.setBrush(QColor('#303039' if self.underMouse() else '#1b1b1e'));
        if self.kind!=2:p.drawEllipse(0,0,37,37)
        p.setPen(QPen(QColor(self.tint),1.6));p.setBrush(Qt.NoBrush)
        if self.kind==0:
            p.drawRoundedRect(10,12,15,15,4,4);p.drawLine(16,21,26,10);p.drawLine(23,10,26,13)
        elif self.kind==1:
            p.drawRoundedRect(16,9,6,13,3,3);p.drawArc(12,12,14,14,180*16,180*16);p.drawLine(19,26,19,30)
        elif self.kind==2:
            g=QRadialGradient(17,14,16);g.setColorAt(0,QColor('#d4e1ff'));g.setColorAt(1,QColor('#739cff'));p.setBrush(g);p.setPen(Qt.NoPen);radius=12.5+self.level*5;p.drawEllipse(QPoint(18,18),int(radius),int(radius))
        else:
            p.drawRect(10,16,4,6);p.drawLine(14,16,20,11);p.drawLine(20,11,20,27);p.drawLine(20,27,14,22);p.drawArc(19,12,10,15,-70*16,140*16);p.drawArc(20,9,13,21,-65*16,130*16)

class CompactVoice(QWidget):
    """Movable voice dock using the existing orb controller and its live state."""
    def __init__(self,orb):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.orb=orb;self.setWindowTitle('NOVA Compact Voice');self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(246,106);layout=QVBoxLayout(self);layout.setContentsMargins(15,5,15,5);layout.setSpacing(7)
        row=QHBoxLayout();row.setContentsMargins(18,0,18,0);row.setSpacing(3)
        self.buttons=[]
        for text,tip,callback in [('✎','Open text chat',orb.toggle),('♩','Start / stop microphone',self.toggle_mic),('●','Start voice / interrupt reply',orb.voice_click),('◖))','Enable / mute spoken replies',self.toggle_audio)]:
            b=VoiceControl(len(self.buttons));b.setFixedSize(37,37);b.setToolTip(tip);b.setAccessibleName(tip);b.clicked.connect(callback);row.addWidget(b);self.buttons.append(b)
        layout.addLayout(row)
        self.status=QLineEdit('Ready');self.status.setReadOnly(True);self.status.setFocusPolicy(Qt.NoFocus);self.status.setFixedHeight(36);self.status.setContentsMargins(13,0,8,0)
        self.status.setStyleSheet('color:#a8a8ad;background:#222225;border:1px solid #454549;border-radius:16px;font-size:11px;')
        layout.addWidget(self.status)
        self.hovered=False;self.fade_effects=[];self.fade_animations=[]
        for widget in [self.buttons[0],self.buttons[1],self.buttons[3],self.status]:
            effect=QGraphicsOpacityEffect(widget);widget.setGraphicsEffect(effect)
            animation=QPropertyAnimation(effect,b'opacity',self);animation.setDuration(350);animation.setEasingCurve(QEasingCurve.InOutQuad)
            self.fade_effects.append(effect);self.fade_animations.append(animation)
        self.idle_fade=QTimer(self);self.idle_fade.setSingleShot(True);self.idle_fade.setInterval(1200);self.idle_fade.timeout.connect(self.fade_idle)
        self.refresh()
    def refresh(self):
        state=self.orb.state;labels={'Idle':'Ready','Thinking':'Thinking / running request','Ready':'Opening microphone…','Listening':'Listening…','Speaking':'Speaking…','Preparing voice':'Preparing voice…','Error':'Check chat for details'}
        text=('Listening: '+self.orb.live_transcript) if state=='Listening' and self.orb.live_transcript else labels.get(state,state)
        self.status.setText(text);self.status.setCursorPosition(len(text));self.status.setToolTip(text)
        for i,b in enumerate(self.buttons):
            color='#a8caff' if i==2 else '#e7e7ea'
            if i==1 and self.orb.voice_chat_active:color='#73c7ff'
            if i==3 and not self.orb.panel.speak.isChecked():color='#77777c'
            b.tint=color;b.update()
        if state=='Idle' and not self.hovered:
            if not self.idle_fade.isActive():self.idle_fade.start()
        else:self.reveal_controls()

    def reveal_controls(self):
        self.idle_fade.stop()
        for widget,animation,effect in zip([self.buttons[0],self.buttons[1],self.buttons[3],self.status],self.fade_animations,self.fade_effects):
            widget.setEnabled(True);animation.stop();animation.setStartValue(effect.opacity());animation.setEndValue(1.0);animation.start()
    def fade_idle(self):
        if self.orb.state!='Idle' or self.hovered:return
        for widget,animation,effect in zip([self.buttons[0],self.buttons[1],self.buttons[3],self.status],self.fade_animations,self.fade_effects):
            widget.setEnabled(False);animation.stop();animation.setStartValue(effect.opacity());animation.setEndValue(0.0);animation.start()
    def enterEvent(self,event):self.hovered=True;self.reveal_controls();super().enterEvent(event)
    def leaveEvent(self,event):
        self.hovered=False
        if self.orb.state=='Idle':self.idle_fade.start()
        super().leaveEvent(event)
    def toggle_mic(self):
        if self.orb.voice_chat_active or self.orb.recorder:self.orb.stop()
        else:self.orb.voice_click()
        self.refresh()
    def toggle_audio(self):
        self.orb.panel.speak.setChecked(not self.orb.panel.speak.isChecked())
        config['voice_muted']=not self.orb.panel.speak.isChecked()
        if not self.orb.panel.speak.isChecked():self.orb.stop()
        self.refresh()
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton:self.start=e.globalPos();self.origin=self.pos()
        elif e.button()==Qt.RightButton:self.orb.tray.contextMenu().popup(e.globalPos())
    def mouseMoveEvent(self,e):
        if e.buttons() & Qt.LeftButton and hasattr(self,'start'):self.move(self.origin+e.globalPos()-self.start)
    def mouseReleaseEvent(self,e):self.orb.settings.setValue('compact-position',self.pos())

class Orb(QWidget):
    def __init__(self):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setWindowTitle('NOVA Blue Orb')
        self.setFixedSize(96,96); self.state='Idle'; self.phase=0.; self.dragged=False
        self.settings=QSettings('NOVA-Tests','Desktop') if os.environ.get('NOVA_TESTING')=='1' else QSettings('NOVA','Desktop'); self.voice=None; self.recorder=None; self.speech_path=None
        self.voice_level=0.;self.live_transcript='';self.voice_chat_active=False;self.no_speech_retries=0;self.listen_pending=False;self.listen_generation=0;self.cue_process=None;self.voice_turn=False
        self.worker=None;self.barge_capture=None;self.partial_worker=None;self.stream_voice=None;self.pending_reply=None;self.streamed_chars=0;self.stream_text=''; self.retired=[]; self.histories={}; self.sessions={}
        self.panel=Panel(self)
        geo=QApplication.primaryScreen().availableGeometry()
        saved=self.settings.value('position',QPoint(geo.right()-130,geo.bottom()-160))
        if not any(s.availableGeometry().contains(saved) for s in QApplication.screens()): saved=QPoint(geo.right()-130,geo.bottom()-160)
        self.move(saved)
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(50)
        pm=QPixmap(64,64); pm.fill(Qt.transparent); p=QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setBrush(QColor('#168fff')); p.setPen(Qt.NoPen); p.drawEllipse(8,8,48,48); p.end()
        self.tray=QSystemTrayIcon(QIcon(pm),self); menu=QMenu()
        menu.addAction('NOVA system overview',self.system_overview);menu.addAction('Start voice conversation',self.voice_click);menu.addAction('Open chat',self.toggle)
        menu.addAction('Toggle compact voice bar / orb',self.toggle_compact);menu.addAction('Choose AI / model',self.choose_model);menu.addAction('Preview neural voice',self.preview_voice);menu.addAction('Stop / mute',self.stop);menu.addSeparator();menu.addAction('Quit NOVA',self.quit)
        self.tray.setContextMenu(menu); self.tray.setToolTip('NOVA — left-click to speak; right-click for chat and models'); self.tray.show()
        self.tray.activated.connect(lambda reason:self.voice_click() if reason==QSystemTrayIcon.Trigger else None)
        self.compact=CompactVoice(self)
        self.compact_mode=self.settings.value('compact-mode',True,type=bool)
        self.apply_compact()
        if os.environ.get('NOVA_TESTING')!='1':
            config['aec_source'],config['aec_sink']=ensure_audio_route()
            turn=TurnWarm();self.retired.append(turn);turn.finished.connect(lambda:self.cleanup(turn));turn.start()
            recognition=RecognitionWarm(config);self.retired.append(recognition);recognition.finished.connect(lambda:self.cleanup(recognition));recognition.start()
            warm=VoiceWarm(config);self.retired.append(warm);warm.finished.connect(lambda:self.cleanup(warm));warm.start()
    def system_overview(self):
        from integration_registry import snapshot
        registry=snapshot()
        if not self.panel.isVisible():self.toggle()
        self.panel.chat.append('NOVA system overview\n'+ '\n'.join(x['name']+': '+('installed' if x['installed'] else 'unavailable') for x in registry['agents'])+'\nModel providers: '+', '.join(x['name'] for x in registry['model_providers'])+'\nShared context: profile and live host facts. Agent tools retain their own permissions. Cross-agent history is not yet unified.')
    def apply_compact(self):
        if self.compact_mode:
            self.hide();position=self.settings.value('compact-position',self.pos());g=QApplication.primaryScreen().availableGeometry()
            self.compact.move(max(g.left(),min(position.x(),g.right()-self.compact.width())),max(g.top(),min(position.y(),g.bottom()-self.compact.height())))
            self.compact.show();self.compact.refresh()
        else:self.compact.hide();self.show()
    def toggle_compact(self):
        self.compact_mode=not self.compact_mode;self.settings.setValue('compact-mode',self.compact_mode);self.apply_compact()
    def tick(self):
        self.phase+=.05;self.voice_level*=.85;self.update()
        self.compact.buttons[2].level=self.voice_level;self.compact.buttons[2].update()
        if self.cue_process and self.cue_process.poll() is not None:self.cue_process=None

    def set_state(self,state):
        previous=self.state;self.state=state;self.panel.status.setText(state);self.update()
        if hasattr(self,'compact'):self.compact.refresh()
        if previous!=state:event('state_changed',previous=previous,state=state)
        runtime(state,self.panel.provider.currentText(),continuous_voice_session=self.voice_chat_active,microphone_active=self.recorder is not None,request_pending=self.worker is not None,speech_active=self.voice is not None,barge_monitor_active=self.barge_capture is not None,listen_pending=self.listen_pending)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        col=QColor('#32aaff' if self.state!='Error' else '#ff8f7e')
        grad=QRadialGradient(44,39,44); grad.setColorAt(0,QColor('#79dcff')); grad.setColorAt(.42,col); grad.setColorAt(.75,QColor(20,110,230,120)); grad.setColorAt(1,QColor(10,70,200,0))
        radius=34+self.voice_level*8+math.sin(self.phase*(5 if self.state in ['Listening','Speaking'] else 1.4))*2
        p.setPen(Qt.NoPen); p.setBrush(grad); p.drawEllipse(QPoint(48,48),int(radius+9),int(radius+9))
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(100,205,255,155),1.5)); p.drawEllipse(14,14,68,68)
        p.save(); p.translate(48,48); p.rotate(-30+self.phase*15); p.drawEllipse(-30,-11,60,22); p.rotate(80); p.drawEllipse(-28,-12,56,24); p.restore()
        if self.state=='Thinking':
            p.setPen(QPen(col,3)); p.drawArc(8,8,80,80,int(self.phase*120*16)%5760,110*16)
        if self.state in ['Listening','Speaking']:
            p.setPen(QPen(col,2)); r=38+math.sin(self.phase*5)*5; p.drawEllipse(QPoint(48,48),int(r),int(r))
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton: self.start=e.globalPos(); self.origin=self.pos(); self.dragged=False
        elif e.button()==Qt.RightButton: self.tray.contextMenu().popup(e.globalPos())
    def mouseMoveEvent(self,e):
        if e.buttons() & Qt.LeftButton:
            delta=e.globalPos()-self.start
            if delta.manhattanLength()>5: self.dragged=True
            if self.dragged: self.move(self.origin+delta)
    def mouseReleaseEvent(self,e):
        if e.button()==Qt.LeftButton:
            if self.dragged: self.settings.setValue('position',self.pos())
            else: self.voice_click()
    def preview_voice(self):
        self.stop();self.speak_text('Hi Damian. I am Nova, your personal assistant. My neural voice is ready.')
    def choose_model(self):
        if not self.panel.isVisible():self.toggle()
        self.panel.provider.setFocus()
    def toggle(self):
        if self.panel.isVisible(): self.panel.hide()
        else:
            g=QApplication.screenAt(self.pos()).availableGeometry() if QApplication.screenAt(self.pos()) else QApplication.primaryScreen().availableGeometry()
            self.panel.move(max(g.left(),min(self.x()-self.panel.width()+96,g.right()-self.panel.width())),max(g.top(),min(self.y()-self.panel.height()-8,g.bottom()-self.panel.height())))
            self.panel.show(); self.panel.raise_(); self.panel.activateWindow(); self.panel.entry.setFocus()
    def fail(self,text):
        self.voice_chat_active=False
        self.set_state('Error'); self.panel.chat.append('Error: '+text); self.panel.set_busy(False)
        event('interaction_failed',error=text)
        self.play_cue('error')
        if self.voice_turn:self.speak_text('Sorry. '+text[:220])
    def play_cue(self,name):
        if self.cue_process and self.cue_process.poll() is None:self.cue_process.terminate()
        try:self.cue_process=subprocess.Popen(playback_command(BASE/'assets/sounds'/(name+'.wav'),config.get('aec_sink')),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError:self.cue_process=None;QApplication.beep()
    def speak_text(self,text):
        self.stop_voice();speech=Speech(text,config);self.voice=speech;self.set_state('Preparing voice')
        speech.playback_started.connect(lambda:self.playback_started(speech))
        speech.error.connect(lambda message:self.speech_failed(speech,message))
        speech.finished.connect(lambda:self.speech_finished(speech));speech.finished.connect(lambda:self.cleanup(speech));speech.start()
    def playback_started(self,speech):
        if self.voice is not speech:return
        self.set_state('Speaking');self.start_barge_monitor()
    def speech_failed(self,speech,message):
        if self.voice is not speech:return
        self.stop()
        self.panel.chat.append('Voice error: '+message);self.set_state('Error');self.play_cue('error')
    def speech_finished(self,speech):
        if self.voice is not speech:return
        self.stop_barge_monitor()
        if self.pending_reply:
            self.histories[self.pending_reply['route']].append({'role':'assistant','content':self.pending_reply['text']})
            self.pending_reply=None
        self.voice=None;self.stream_voice=None;self.voice_turn=False
        if self.state!='Error':
            self.set_state('Idle')
            if self.voice_chat_active:
                generation=self.listen_generation
                QTimer.singleShot(350,lambda:self.resume_conversation(generation))
    def resume_conversation(self,generation):
        if self.voice_chat_active and generation==self.listen_generation and not self.worker and not self.voice and not self.recorder and not self.listen_pending:
            self.record(auto_send=True)

    def send(self):
        text=self.panel.entry.text().strip()
        self.submit(text)
    def submit(self,text,voice_reply=False):
        if not text or self.worker or self.recorder or self.listen_pending: return
        if self.panel.model.isEnabled() and self.panel.model.currentText()!=self.panel.model.itemText(self.panel.model.currentIndex()):
            self.fail('Choose a model from the matching results before sending.');return
        self.stop_voice(); provider=self.panel.provider.currentText()
        model=self.panel.model.currentData(); route=route_key(provider,model)
        history=self.histories.setdefault(route,[]); history.append({'role':'user','content':text})
        self.panel.chat.append('You → '+route+': '+text)
        if not voice_reply:self.panel.entry.clear()
        self.set_state('Thinking');self.panel.set_busy(True)
        session=self.sessions.setdefault(route,str(uuid.uuid4()))
        task=Task(provider,history[-12:].copy(),session,model); task.voice_reply=voice_reply;task.tools_enabled=self.panel.tools.isChecked();self.voice_turn=voice_reply;self.worker=task
        if (voice_reply or self.panel.speak.isChecked()) and not config.get('voice_muted',False):
            self.streamed_chars=0;self.stream_text='';self.pending_reply={'route':route,'text':''}
            speech=StreamSpeech(config);self.stream_voice=speech;self.voice=speech
            speech.playback_started.connect(lambda:self.playback_started(speech))
            speech.error.connect(lambda message:self.speech_failed(speech,message))
            speech.finished.connect(lambda:self.speech_finished(speech));speech.finished.connect(lambda:self.cleanup(speech));speech.start()
            task.delta.connect(lambda fragment:self.stream_fragment(task,fragment))
            self.start_barge_monitor()
        task.result.connect(lambda text:self.received(task,route,text)); task.error.connect(lambda text:self.failed_task(task,route,text))
        task.finished.connect(lambda:self.cleanup(task)); task.start()
    def stream_fragment(self,task,fragment):
        if self.worker is task and self.stream_voice and self.voice is self.stream_voice:
            self.streamed_chars+=len(fragment);self.stream_text+=fragment;self.stream_voice.add_text(fragment)
    def cleanup(self,task):
        if task in self.retired: self.retired.remove(task)
        task.deleteLater()
    def failed_task(self,task,provider,text):
        if self.worker is not task:return
        self.worker=None;self.stop_voice();self.stop_barge_monitor()
        history=self.histories.get(provider,[])
        if history and history[-1]['role']=='user': history.pop()
        self.stop_voice();self.stop_barge_monitor();self.fail(text)
    def received(self,task,provider,text):
        if self.worker is not task:return
        self.worker=None;self.panel.chat.append(provider+': '+text);self.panel.set_busy(False)
        if self.stream_voice and self.voice is self.stream_voice:
            self.pending_reply['text']=text
            if not self.stream_text.endswith(text):self.stream_voice.add_text(text)
            self.stream_voice.finish_input()
        else:
            self.histories[provider].append({'role':'assistant','content':text});self.set_state('Idle')
            if (getattr(task,'voice_reply',False) or self.panel.speak.isChecked()) and not config.get('voice_muted',False):self.speak_text(text)
            elif self.voice_chat_active:self.resume_conversation(self.listen_generation)
    def stop_voice(self):
        if self.voice:
            speech=self.voice
            if self.pending_reply and isinstance(speech,StreamSpeech):
                heard=speech.spoken_text.strip()
                if speech.partial_text:heard+=' [The following sentence was interrupted before completion.]'
                if heard:self.histories[self.pending_reply['route']].append({'role':'assistant','content':heard})
            self.pending_reply=None;self.stream_voice=None
            speech.cancel();self.retired.append(speech);self.voice=None
            event('tts_cancelled')
    def start_barge_monitor(self):
        if not self.voice_chat_active or not config.get('barge_in_enabled') or not config.get('aec_source') or self.barge_capture or self.recorder:return
        capture=Capture(True,config['voice_threshold'],config['voice_silence_seconds'],idle_timeout=0,source=config['aec_source'],monitor=True,endpoint=adaptive_endpoint if config.get('adaptive_turns') else None)
        self.barge_capture=capture
        capture.speech_onset.connect(lambda:self.barge_onset(capture))
        capture.level.connect(lambda level:self.microphone_level(capture,level))
        capture.partial.connect(lambda path:self.partial_capture(capture,path))
        capture.result.connect(lambda path:self.barge_finished(capture,path))
        capture.error.connect(lambda error:self.barge_failed(capture,error))
        capture.finished.connect(lambda:self.cleanup(capture));capture.start()
        event('barge_monitor_started')
    def stop_barge_monitor(self):
        if self.barge_capture:
            capture=self.barge_capture;self.barge_capture=None;capture.cancel();self.retired.append(capture)
    def barge_onset(self,capture):
        if self.barge_capture is not capture:return
        self.barge_capture=None
        active=self.voice_chat_active;self.stop();self.voice_chat_active=active
        self.recorder=capture;self.set_state('Listening');self.panel.set_busy(True);self.panel.mic.setEnabled(True);self.panel.mic.setText('Finish recording')
        event('spoken_interruption',remaining_generation_may_continue_remotely=True)
    def barge_finished(self,capture,path):
        if self.recorder is capture:self.capture_finished(capture,path)
        else:Path(path).unlink(missing_ok=True)
    def barge_failed(self,capture,error):
        if self.barge_capture is capture:
            self.barge_capture=None;config['barge_in_enabled']=False
            self.panel.chat.append('Spoken interruption unavailable; click interruption remains available.')
            event('barge_monitor_failed',error=error)
        elif self.recorder is capture:self.capture_failed(capture,error)
    def partial_capture(self,capture,path):
        if config.get('stt_provider')!='groq' or self.recorder is not capture or self.partial_worker:
            Path(path).unlink(missing_ok=True);return
        task=Transcribe(path,partial=True);self.partial_worker=task
        task.result.connect(lambda text:self.partial_transcribed(capture,task,text))
        task.finished.connect(lambda:self.partial_finished(task));task.start()
    def partial_transcribed(self,capture,task,text):
        if self.recorder is capture and self.partial_worker is task:
            self.live_transcript=text;self.compact.refresh();self.panel.transcript.setText('Hearing: '+text);event('partial_transcript',text=text)
    def partial_finished(self,task):
        if self.partial_worker is task:self.partial_worker=None
        if task in self.retired:self.retired.remove(task)
        task.deleteLater()
    def microphone_level(self,capture,level):
        if self.recorder is capture:self.voice_level=max(level,self.voice_level*.7)
    def voice_click(self):
        if self.listen_pending:self.stop();return
        if self.recorder:self.recorder.finish();return
        self.stop();self.voice_chat_active=True;self.no_speech_retries=0
        event('voice_conversation_started')
        self.record(auto_send=True)
    def record(self,auto_send=False):
        if self.recorder:self.recorder.finish();return
        if self.worker or self.listen_pending:return
        if getattr(self.panel,'discovery',None) is not None and self.panel.discovery.isRunning():return
        self.stop_voice();self.voice_turn=bool(auto_send);self.listen_pending=True
        self.listen_generation+=1;generation=self.listen_generation
        self.panel.set_busy(True);self.play_cue('listen-start');self.set_state('Ready')
        self.await_start_cue(generation,auto_send)
    def await_start_cue(self,generation,auto_send):
        if generation!=self.listen_generation or not self.listen_pending:return
        if self.cue_process and self.cue_process.poll() is None:
            QTimer.singleShot(30,lambda:self.await_start_cue(generation,auto_send));return
        self.listen_pending=False;self.live_transcript='';self.voice_level=0.
        capture=Capture(auto_send,config['voice_threshold'],config['voice_silence_seconds'],idle_timeout=config.get('voice_idle_timeout',0) if self.voice_chat_active else 8,source=config.get('aec_source'),endpoint=adaptive_endpoint if config.get('adaptive_turns') else None);self.recorder=capture
        capture.level.connect(lambda level:self.microphone_level(capture,level))
        capture.partial.connect(lambda path:self.partial_capture(capture,path))
        capture.idle.connect(lambda:self.capture_idle(capture))
        capture.ready.connect(lambda:self.capture_ready(capture))
        capture.result.connect(lambda path:self.capture_finished(capture,path))
        capture.error.connect(lambda error:self.capture_failed(capture,error))
        capture.finished.connect(lambda:self.cleanup(capture));capture.start()
    def capture_ready(self,capture):
        if self.recorder is not capture:return
        event('microphone_started',auto_send=capture.auto_send)
        self.set_state('Listening');self.panel.mic.setEnabled(True);self.panel.mic.setText('Finish recording')
    def capture_finished(self,capture,path):
        if self.recorder is not capture:Path(path).unlink(missing_ok=True);return
        event('microphone_stopped',reason='speech_endpoint_or_manual_finish')
        self.recorder=None
        if self.partial_worker:
            partial=self.partial_worker;self.partial_worker=None;partial.cancel();self.retired.append(partial)
        self.play_cue('listen-stop');self.panel.mic.setText('Record voice');self.set_state('Thinking')
        task=Transcribe(path,capture.auto_send);self.worker=task
        task.result.connect(lambda text:self.transcribed(task,text));task.error.connect(lambda text:self.transcription_failed(task,text))
        task.finished.connect(lambda:self.cleanup(task));task.start()
    def capture_idle(self,capture):
        if self.recorder is not capture:return
        self.recorder=None;self.stop();self.panel.status.setText('Recording ended after '+str(capture.idle_timeout)+' seconds of silence')
        event('voice_conversation_ended',reason='idle_timeout')
    def capture_failed(self,capture,error):
        if self.recorder is not capture:return
        self.recorder=None;self.play_cue('listen-stop');self.panel.mic.setText('Record voice');self.fail(error)
    def transcribed(self,task,text):
        if self.worker is not task:return
        event('transcription_completed',transcript=text,auto_send=task.auto_send)
        self.worker=None;self.panel.set_busy(False);self.set_state('Idle')
        if task.auto_send:
            if text.lower().strip(' .!?') in ['stop','stop listening','end conversation','goodbye','bye nova','stop nova']:
                self.stop();self.speak_text('Okay. Voice conversation ended.');return
            self.no_speech_retries=0;self.submit(text,voice_reply=True)
        else:
            self.panel.entry.setText(text);self.panel.chat.append('Voice transcript ready — edit it, then Send.');self.panel.entry.setFocus()
    def transcription_failed(self,task,text):
        if self.worker is not task:return
        self.worker=None
        if self.voice_chat_active and 'No speech detected' in text and self.no_speech_retries<1:
            self.no_speech_retries+=1;self.panel.set_busy(False);self.set_state('Idle');event('voice_unrecognized',retry=1)
            self.resume_conversation(self.listen_generation);return
        self.fail(text)
    def stop(self):
        if self.voice_chat_active:event('voice_conversation_ended',reason='stopped')
        self.voice_chat_active=False
        self.stop_voice();self.stop_barge_monitor();self.voice_turn=False
        if self.partial_worker:
            task=self.partial_worker;self.partial_worker=None;task.cancel();self.retired.append(task)
        was_listening=self.listen_pending or self.recorder is not None
        self.listen_pending=False;self.listen_generation+=1
        if self.recorder:
            capture=self.recorder;capture.cancel();self.retired.append(capture);self.recorder=None
        if was_listening:event('microphone_stopped',reason='cancelled');self.play_cue('listen-stop')
        if self.worker:
            task=self.worker; task.cancel(); self.retired.append(task); self.worker=None
            if isinstance(task,Task):
                history=self.histories.get(task.route,[])
                if history and history[-1]['role']=='user':history.pop()
        self.panel.mic.setText('Record voice'); self.panel.set_busy(False); self.set_state('Idle')
    def quit(self):
        self.stop()
        for task in self.retired: task.wait(5000)
        if any(task.isRunning() for task in self.retired):
            QTimer.singleShot(500,self.quit); return
        if getattr(self.panel,'discovery',None) is not None and self.panel.discovery.isRunning():
            QTimer.singleShot(500,self.quit);return
        self.settings.setValue('position',self.pos()); QApplication.quit()

class CatalogRefresh(QThread):
    done=pyqtSignal(str)
    def run(self):
        try:refresh_router();self.done.emit('')
        except Exception as e:self.done.emit(str(e))

class Panel(QWidget):
    def __init__(self,orb):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.orb=orb; self.setWindowTitle('NOVA Assistant'); self.resize(430,570)
        self.setStyleSheet('QWidget{background:#101b2c;color:#e6f3ff;font-size:13px;} QPushButton,QComboBox,QLineEdit{background:#1a2b43;border:1px solid #304e71;border-radius:8px;padding:9px;} QPushButton:hover{background:#254365;} QPlainTextEdit{background:#0d1624;border:1px solid #263e59;border-radius:8px;padding:8px;}')
        layout=QVBoxLayout(self); layout.setContentsMargins(18,18,18,18)
        row=QHBoxLayout(); title=QLabel('NOVA'); title.setStyleSheet('font-size:20px;font-weight:600;'); row.addWidget(title); row.addStretch()
        close=QPushButton('×'); close.clicked.connect(self.hide); row.addWidget(close); layout.addLayout(row)
        self.catalog=catalogs(config);self.provider=QComboBox(); self.provider.addItems(list(self.catalog)); self.provider.setCurrentText(str(orb.settings.value('provider-choice','OpenClaw'))); layout.addWidget(self.provider)
        self.model=QComboBox(); self.model.setEditable(True); self.model.setInsertPolicy(QComboBox.NoInsert)
        self.model.completer().setFilterMode(Qt.MatchContains); self.model.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.model.setMinimumContentsLength(20); self.model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        layout.addWidget(self.model)
        self.refresh=QPushButton('Refresh model catalogs');layout.addWidget(self.refresh);self.refresh.clicked.connect(self.refresh_catalogs)
        self.route=QLabel(); self.route.setWordWrap(True); layout.addWidget(self.route)
        self.provider.currentTextChanged.connect(self.provider_changed);self.model.currentIndexChanged.connect(self.route_changed)
        self.provider_changed()
        self.status=QLabel('Idle'); layout.addWidget(self.status)
        self.transcript=QLabel('');self.transcript.setWordWrap(True);layout.addWidget(self.transcript)
        self.chat=QPlainTextEdit(); self.chat.append=self.chat.appendPlainText; self.chat.setReadOnly(True); self.chat.setPlainText('NOVA is ready. Left-click the orb to speak; right-click for chat and models.\nOrb voice turns send automatically and speak the answer. Recording here lets you edit before sending.'); layout.addWidget(self.chat)
        self.entry=QLineEdit(); self.entry.setPlaceholderText('Type a message…'); self.entry.returnPressed.connect(orb.send); layout.addWidget(self.entry)
        row=QHBoxLayout(); self.send_button=QPushButton('Send'); self.send_button.clicked.connect(orb.send); row.addWidget(self.send_button)
        self.mic=QPushButton('Record voice'); self.mic.clicked.connect(orb.record); row.addWidget(self.mic)
        stop=QPushButton('Stop'); stop.clicked.connect(orb.stop); row.addWidget(stop); layout.addLayout(row)
        self.stt_choice=QComboBox();self.stt_choice.addItem('Fast recognition · Groq cloud (audio uploaded)','groq');self.stt_choice.addItem('Private recognition · local Whisper','local')
        self.stt_choice.setCurrentIndex(0 if config.get('stt_provider')=='groq' else 1);self.stt_choice.currentIndexChanged.connect(self.stt_changed);layout.addWidget(self.stt_choice)
        self.voice_choice=QComboBox();self.voice_choice.addItem('Neural voice: natural / fast',str(BASE/'assets/voices/en_US-lessac-medium.onnx'));self.voice_choice.addItem('Neural voice: high quality',str(BASE/'assets/voices/en_US-lessac-high.onnx'))
        self.voice_choice.addItem('Groq Hannah · cloud, requires terms acceptance','groq:hannah');self.voice_choice.addItem('Groq Troy · cloud, requires terms acceptance','groq:troy')
        self.voice_choice.setCurrentIndex((2 if config.get('groq_voice','hannah')=='hannah' else 3) if config.get('tts_provider')=='groq' else (1 if config['tts_model'].endswith('high.onnx') else 0));self.voice_choice.currentIndexChanged.connect(self.voice_changed);layout.addWidget(self.voice_choice)
        self.tools=QCheckBox('Enable system tools / agent delegation');self.tools.setChecked(True);layout.addWidget(self.tools)
        self.speak=QCheckBox('Speak replies (neural voice)');self.speak.setChecked(orb.settings.value('speak-replies',True,type=bool));self.speak.toggled.connect(lambda checked:orb.settings.setValue('speak-replies',checked));layout.addWidget(self.speak)
        self.volume_label=QLabel('Voice volume: '+str(config['tts_volume_percent'])+'%');layout.addWidget(self.volume_label)
        self.volume=QSlider(Qt.Horizontal);self.volume.setRange(0,200);self.volume.setValue(int(config['tts_volume_percent']));self.volume.valueChanged.connect(self.volume_changed);layout.addWidget(self.volume)
        note=QLabel('Left-click orb: talk · right-click: chat / models / stop'); note.setStyleSheet('color:#8aa7c6;font-size:11px'); layout.addWidget(note)
    def volume_changed(self,value):
        config['tts_volume_percent']=value;self.volume_label.setText('Voice volume: '+str(value)+'%')
        if os.environ.get('NOVA_TESTING')!='1':
            CONFIG.write_text(json.dumps(config,indent=2)+'\n');CONFIG.chmod(0o600);event('voice_volume_selected',percent=value)
    def stt_changed(self):
        config['stt_provider']=self.stt_choice.currentData()
        if os.environ.get('NOVA_TESTING')!='1':CONFIG.write_text(json.dumps(config,indent=2)+'\n');CONFIG.chmod(0o600)
        event('recognition_provider_selected',provider=config['stt_provider'])
    def voice_changed(self):
        selected=self.voice_choice.currentData()
        config['tts_provider']='groq' if selected.startswith('groq:') else 'local'
        if config['tts_provider']=='groq':config['groq_voice']=selected.split(':')[1]
        else:config['tts_model']=selected
        if os.environ.get('NOVA_TESTING')!='1':CONFIG.write_text(json.dumps(config,indent=2)+'\n');CONFIG.chmod(0o600)
        event('voice_selected',voice=config['tts_model'])
    def set_busy(self,busy):
        self.send_button.setEnabled(not busy); self.provider.setEnabled(not busy); self.model.setEnabled(not busy and bool(self.catalog.get(self.provider.currentText()))); self.refresh.setEnabled(not busy); self.mic.setEnabled(not busy);self.tools.setEnabled(not busy);self.voice_choice.setEnabled(not busy);self.stt_choice.setEnabled(not busy)
    def provider_changed(self):
        p=self.provider.currentText();self.model.blockSignals(True);self.model.clear()
        for item in self.catalog.get(p,[]):
            label=item.get('display_name',item['model'])
            if p=='Managed Free Models':label=item['provider']+' · '+label
            self.model.addItem(label,item)
            self.model.setItemData(self.model.count()-1,item['model'],Qt.ToolTipRole)
        if p=='Managed Free Models':
            wanted=managed_config().get('fallback',{}).get('default_free_model')
            for i in range(self.model.count()):
                if self.model.itemData(i)['model']==wanted:self.model.setCurrentIndex(i);break
        remembered=self.orb.settings.value('model-choice/'+p,None)
        for i in range(self.model.count()):
            item=self.model.itemData(i)
            if route_key(p,item)==remembered or (not remembered and p=='Ollama' and item['model']==config['ollama_model']):
                self.model.setCurrentIndex(i);break
        if not self.model.count():self.model.addItem('Configured agent' if p in ['OpenClaw','Codex Agent','Cursor Agent'] else 'No catalog entries',None)
        self.model.setEnabled(bool(self.catalog.get(p)));self.model.blockSignals(False);self.route_changed()
    def route_changed(self):
        p=self.provider.currentText();entry=self.model.currentData()
        self.orb.settings.setValue('provider-choice',p)
        if entry:self.orb.settings.setValue('model-choice/'+p,route_key(p,entry))
        self.route.setText('System assistant · OpenClaw tools, browser and plugin bridges' if p=='OpenClaw' else 'Installed agent with its configured tools' if p in ['Codex Agent','Cursor Agent'] else
             (route_key(p,entry)+'\nShared system context; tool tasks use agent delegation.') if entry else 'Refresh the model catalog before sending.')
    def refresh_catalogs(self):
        self.set_busy(True);self.discovery=CatalogRefresh();self.discovery.done.connect(self.catalog_refreshed)
        self.discovery.finished.connect(self.discovery.deleteLater);self.discovery.finished.connect(lambda:setattr(self,'discovery',None));self.discovery.start()
    def catalog_refreshed(self,error):
        p=self.provider.currentText();self.catalog=catalogs(config);self.provider.blockSignals(True)
        self.provider.clear();self.provider.addItems(list(self.catalog));self.provider.setCurrentText(p)
        self.provider.blockSignals(False);self.provider_changed();self.set_busy(False)
        if error:self.chat.append('Catalog refresh: '+error)
        else:self.chat.append('Model catalogs refreshed from Cursor configuration and 9router.')
    def keyPressEvent(self,e):
        if e.key()==Qt.Key_Escape: self.hide()
        else: super().keyPressEvent(e)

if __name__=='__main__':
    import fcntl
    lock=open(DATA/'desktop.lock','w')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: print('NOVA is already running. Use its orb or tray menu.'); sys.exit(0)
    app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False); app.setApplicationName('NOVA')
    from integration_registry import snapshot
    snapshot()
    orb=Orb();event('application_started',pid=os.getpid(),voice=config['tts_model']);runtime('Idle',orb.panel.provider.currentText()); signal.signal(signal.SIGTERM,lambda *_:orb.quit()); signal.signal(signal.SIGINT,lambda *_:orb.quit())
    sys.exit(app.exec_())
