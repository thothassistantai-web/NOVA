"""Regression coverage for streaming boundaries and interruption ownership."""
import os,unittest
os.environ['NOVA_TESTING']='1'
from unittest.mock import Mock,patch
from PyQt5.QtWidgets import QApplication
from speech_output import SentenceBuffer,StreamSpeech
import nova
app=QApplication.instance() or QApplication([])
class StreamingTests(unittest.TestCase):
    def test_microphone_feedback_ignores_old_capture(self):
        orb=nova.Orb();current=Mock();orb.recorder=current;orb.microphone_level(current,.8)
        self.assertEqual(orb.voice_level,.8);orb.microphone_level(Mock(),1.0);self.assertEqual(orb.voice_level,.8)
        task=Mock();orb.partial_worker=task;orb.set_state('Listening');text='hey nova '+('keep these latest words visible '*8)
        orb.partial_transcribed(current,task,text)
        self.assertEqual(orb.compact.status.text(),'Listening: '+text);self.assertEqual(orb.compact.status.cursorPosition(),len('Listening: '+text))
        orb.recorder=None;orb.partial_worker=None;orb.stop();orb.compact.hide();orb.timer.stop();orb.panel.hide();orb.hide();orb.tray.hide()
    def test_compact_status_uses_controller_state(self):
        orb=nova.Orb();orb.set_state('Listening')
        self.assertEqual(orb.compact.status.text(),'Listening…')
        with patch.object(orb,'voice_click') as start:orb.compact.toggle_mic();start.assert_called_once()
        orb.stop();orb.compact.hide();orb.timer.stop();orb.panel.hide();orb.hide();orb.tray.hide()
    def test_sse_fragments_arrive_before_final_return(self):
        from agent_backend import request_message
        import threading,json
        task=Mock();task.cancelled=threading.Event()
        response=Mock();response.ok=True;response.headers={'Content-Type':'text/event-stream'}
        response.iter_lines.return_value=[b'data: '+json.dumps({'choices':[{'delta':{'content':'Hello '}}]}).encode(),b'data: '+json.dumps({'choices':[{'delta':{'content':'world.'}}]}).encode(),b'data: [DONE]']
        with patch('agent_backend.requests.post',return_value=response):result=request_message(task,'http://test','test','test',[],False)
        self.assertEqual(result['content'],'Hello world.')
        self.assertEqual([c.args[0] for c in task.delta.emit.call_args_list],['Hello ','world.'])
    def test_incomplete_text_is_not_spoken_until_a_boundary(self):
        buffer=SentenceBuffer()
        self.assertEqual(buffer.feed('The weather is'),[])
        self.assertEqual(buffer.feed(' sunny today. '),['The weather is sunny today.'])
        self.assertEqual(buffer.feed('More details',final=True),['More details'])
    def test_short_intro_does_not_block_a_complete_following_sentence(self):
        buffer=SentenceBuffer();self.assertEqual(buffer.feed('Hi. I can help you with that. '),['Hi. I can help you with that.'])
    def test_final_reply_waits_for_playback_before_history_commit(self):
        orb=nova.Orb();task=nova.Task('NVIDIA',[],'test');orb.worker=task;orb.histories['NVIDIA']=[]
        speech=Mock();orb.voice=speech;orb.stream_voice=speech;orb.pending_reply={'route':'NVIDIA','text':''};orb.stream_text=''
        orb.received(task,'NVIDIA','The answer is ready.')
        self.assertEqual(orb.histories['NVIDIA'],[]);speech.add_text.assert_called_once_with('The answer is ready.');speech.finish_input.assert_called_once()
        with patch.object(nova.QTimer,'singleShot'):orb.speech_finished(speech)
        self.assertEqual(orb.histories['NVIDIA'][0]['content'],'The answer is ready.')
        orb.stop();orb.timer.stop();orb.panel.hide();orb.hide();orb.tray.hide()
    def test_spoken_interruption_retains_capture_and_cancels_previous_generation(self):
        orb=nova.Orb();capture=Mock();orb.barge_capture=capture;orb.voice_chat_active=True
        task=Mock();orb.worker=task
        orb.barge_onset(capture)
        self.assertIs(orb.recorder,capture);self.assertIsNone(orb.barge_capture);self.assertTrue(orb.voice_chat_active)
        task.cancel.assert_called_once();self.assertEqual(orb.state,'Listening')
        orb.stop();orb.timer.stop();orb.panel.hide();orb.hide();orb.tray.hide()
if __name__=='__main__':unittest.main()
