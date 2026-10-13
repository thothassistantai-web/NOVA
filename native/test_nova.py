"""Behavior checks for native overlay controls; run with QT_QPA_PLATFORM=offscreen."""
import unittest
import os
os.environ['NOVA_TESTING']='1'
from unittest.mock import patch
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt,QPoint
from PyQt5.QtTest import QTest
import nova
app=QApplication.instance() or QApplication([])
class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.orb=nova.Orb()
    def test_spoken_replies_are_enabled_on_first_launch(self):
        self.orb.settings.remove('speak-replies')
        panel=nova.Panel(self.orb)
        self.assertTrue(panel.speak.isChecked());panel.hide()
    def test_voice_volume_has_an_adjustable_boost(self):
        self.orb.panel.volume.setValue(125)
        self.assertEqual(nova.config['tts_volume_percent'],125)
        self.assertIn('125%',self.orb.panel.volume_label.text())
    def tearDown(self):
        self.orb.stop(); self.orb.timer.stop(); self.orb.panel.hide(); self.orb.hide(); self.orb.tray.hide()
    def test_left_click_starts_voice_without_opening_chat(self):
        with patch.object(self.orb,'record') as record:
            QTest.mouseClick(self.orb,Qt.LeftButton,pos=QPoint(48,48))
            record.assert_called_once_with(auto_send=True)
            self.assertFalse(self.orb.panel.isVisible())
    def test_right_menu_opens_chat_and_escape_hides_it(self):
        action=next(a for a in self.orb.tray.contextMenu().actions() if a.text()=='Open chat')
        action.trigger();self.assertTrue(self.orb.panel.isVisible())
        QTest.keyClick(self.orb.panel,Qt.Key_Escape);self.assertFalse(self.orb.panel.isVisible())
    def test_voice_transcript_is_submitted_automatically(self):
        task=nova.Transcribe('/unused-test.wav',auto_send=True);self.orb.worker=task
        with patch.object(self.orb,'submit') as submit:
            self.orb.transcribed(task,'hello nova')
            submit.assert_called_once_with('hello nova',voice_reply=True)
    def test_voice_reply_is_spoken_even_when_text_speech_is_unchecked(self):
        task=nova.Task('Ollama',[],'test');task.voice_reply=True;self.orb.worker=task
        self.orb.histories['Ollama']=[];self.orb.panel.speak.setChecked(False)
        with patch.object(self.orb,'speak_text') as speak:
            self.orb.received(task,'Ollama','hello')
            speak.assert_called_once_with('hello')
    def test_second_click_finishes_capture(self):
        from unittest.mock import Mock
        capture=Mock();self.orb.recorder=capture
        self.orb.voice_click();capture.finish.assert_called_once()
        self.orb.recorder=None
    def test_reply_completion_resumes_active_voice_session(self):
        from unittest.mock import Mock
        voice=Mock();self.orb.voice=voice;self.orb.voice_chat_active=True;self.orb.state='Speaking'
        with patch.object(nova.QTimer,'singleShot') as timer:
            self.orb.speech_finished(voice)
            callback=timer.call_args.args[1]
            with patch.object(self.orb,'record') as record:
                callback();record.assert_called_once_with(auto_send=True)
    def test_stop_invalidates_a_scheduled_listening_restart(self):
        generation=self.orb.listen_generation;self.orb.voice_chat_active=True;self.orb.stop()
        with patch.object(self.orb,'record') as record:
            self.orb.resume_conversation(generation);record.assert_not_called()
        self.assertFalse(self.orb.voice_chat_active)
    def test_spoken_stop_ends_session_without_calling_ai(self):
        task=nova.Transcribe('/unused-test.wav',auto_send=True);self.orb.worker=task;self.orb.voice_chat_active=True
        with patch.object(self.orb,'submit') as submit,patch.object(self.orb,'speak_text'):
            self.orb.transcribed(task,'stop listening');submit.assert_not_called()
        self.assertFalse(self.orb.voice_chat_active)
    def test_stale_result_cannot_enter_conversation(self):
        self.orb.histories['Ollama']=[]
        stale=nova.Task('Ollama',[],'test')
        self.orb.received(stale,'Ollama','must be ignored')
        self.assertEqual(self.orb.histories['Ollama'],[])
    def test_cancel_removes_unanswered_turn(self):
        task=nova.Task('Ollama',[],'test'); self.orb.worker=task
        self.orb.histories['Ollama']=[{'role':'user','content':'pending'}]
        self.orb.set_state('Thinking');self.orb.stop()
        self.assertIsNone(self.orb.worker);self.assertEqual(self.orb.state,'Idle')
        self.assertEqual(self.orb.histories['Ollama'],[])
    def test_missing_cloud_key_fails_without_rerouting(self):
        errors=[]; task=nova.Task('OpenAI API',[{'role':'user','content':'test'}],'test')
        import os
        key=os.environ.pop('OPENAI_API_KEY',None)
        try:
            task.error.connect(errors.append);task.run()
            self.assertTrue(errors);self.assertIn('not configured',errors[0])
        finally:
            if key: os.environ['OPENAI_API_KEY']=key
class VoiceEndpointTests(unittest.TestCase):
    def test_background_silence_never_counts_as_a_spoken_turn(self):
        from voice_capture import EndpointDetector
        d=EndpointDetector();quiet=b'\x00\x00'*1600
        for _ in range(90):self.assertFalse(d.feed(quiet))
        self.assertEqual(d.speech,0)
    def test_short_noise_bursts_do_not_accumulate_into_speech(self):
        from voice_capture import EndpointDetector
        import struct
        d=EndpointDetector(classifier=lambda frame,rate:frame[:2]==struct.pack('<h',1000))
        burst=struct.pack('<h',1000)*1600;quiet=b'\x00\x00'*3200
        for _ in range(40):
            self.assertFalse(d.feed(burst));self.assertFalse(d.feed(quiet))
        self.assertEqual(d.speech,0)
    def test_brief_pause_preserves_turn_then_long_pause_ends_it(self):
        from voice_capture import EndpointDetector
        import struct
        d=EndpointDetector(classifier=lambda frame,rate:frame[:2]==struct.pack('<h',1000));speech=struct.pack('<h',1000)*1600;quiet=b'\x00\x00'*1600
        for _ in range(3):self.assertFalse(d.feed(speech))
        for _ in range(8):self.assertFalse(d.feed(quiet))
        self.assertFalse(d.feed(speech))
        for _ in range(12):self.assertFalse(d.feed(quiet))
        self.assertTrue(d.feed(quiet))
class ContextAndLoggingTests(unittest.TestCase):
    def test_clock_and_confirmed_location_do_not_require_a_model(self):
        from system_context import local_answer
        self.assertIn('EDT',local_answer('what time is it').replace('EST','EDT'))
        self.assertIn('Queens',local_answer('where am I'))
        task=nova.Task('OpenClaw',[{'role':'user','content':'what time is it'}],'test')
        answers=[];task.result.connect(answers.append)
        with patch.object(nova,'run_agent') as agent:
            task.run();agent.assert_not_called();self.assertTrue(answers)
    def test_secret_redaction_preserves_debug_content(self):
        from behavior_log import clean
        result=clean({'error':'Bearer abcdef0123456789 api_key=private-token','api_key':'hidden','event':'test'})
        self.assertNotIn('abcdef',result['error']);self.assertNotIn('private-token',result['error'])
        self.assertEqual(result['api_key'],'[REDACTED]');self.assertEqual(result['event'],'test')
    def test_model_tool_call_is_executed_and_result_returned(self):
        import agent_backend
        task=nova.Task('NVIDIA',[{'role':'user','content':'check time using tools'}],'test')
        replies=[{'role':'assistant','content':'','tool_calls':[{'id':'call_1','type':'function','function':{'name':'get_system_context','arguments':'{}'}}]}, {'role':'assistant','content':'The clock is available.'}]
        with patch.object(agent_backend,'request_message',side_effect=replies) as request:
            answer=agent_backend.chat_with_tools(task,'https://example.test/v1','test','model',task.messages)
            self.assertEqual(answer,'The clock is available.')
            history=request.call_args.args[4]
            self.assertEqual(history[-1]['role'],'tool');self.assertIn('current_time',history[-1]['content'])
class ModelRoutingTests(unittest.TestCase):
    def test_catalog_matches_managed_configuration(self):
        from model_routes import catalogs,managed_config
        c=catalogs(nova.config);chain=managed_config()['chain']
        self.assertEqual([(m['provider'],m['model']) for m in c['Managed Free Models']],[(m['provider'],m['model']) for m in chain])
        self.assertTrue(c['9router']);self.assertTrue(c['NVIDIA'])
    def test_provider_model_sessions_are_separate(self):
        from model_routes import route_key
        a=route_key('NVIDIA',{'provider':'nvidia','model':'a'})
        b=route_key('NVIDIA',{'provider':'nvidia','model':'b'})
        other=route_key('9router',{'provider':'9router','model':'a'})
        self.assertEqual(len({a,b,other}),3)
    def test_explicit_model_and_endpoint_used_for_request(self):
        from unittest.mock import patch
        class Response:
            ok=True
            headers={'Content-Type':'text/event-stream'}
            def iter_lines(self):
                yield b'data: {"choices":[{"delta":{"content":"ready"}}]}'
                yield b'data: [DONE]'
            def close(self):pass
        model={'provider':'openrouter','model':'test:free'}
        task=nova.Task('Managed Free Models',[{'role':'user','content':'hello'}],'test',model)
        answers=[];task.result.connect(answers.append)
        with patch.object(nova,'credential',return_value=('https://example.test/v1','test-secret')),patch.object(nova.requests,'post',return_value=Response()) as request:
            task.run()
            self.assertEqual(request.call_args.args[0],'https://example.test/v1/chat/completions')
            body=request.call_args.kwargs['json'];self.assertEqual(body['model'],'test:free')
            self.assertEqual(body['provider']['max_price'],{'prompt':0,'completion':0})
            self.assertEqual(answers,['ready'])
if __name__=='__main__': unittest.main()
