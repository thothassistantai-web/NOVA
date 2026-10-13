"""Interaction regressions for the compact voice controls."""
import os
os.environ['NOVA_TESTING']='1'
import unittest
from unittest.mock import Mock,patch
from PyQt5.QtWidgets import QApplication
import nova
app=QApplication.instance() or QApplication([])
class CompactTests(unittest.TestCase):
 def setUp(self):
  self.saved=dict(nova.config);self.orb=nova.Orb();self.orb.panel.speak.setChecked(True)
 def tearDown(self):
  self.orb.worker=None;self.orb.voice=None;self.orb.stop();self.orb.timer.stop();self.orb.compact.close();self.orb.panel.close();self.orb.close();self.orb.tray.hide();nova.config.clear();nova.config.update(self.saved)
 def test_mute_preserves_active_listening(self):
  self.orb.voice_chat_active=True
  with patch.object(self.orb,'stop') as stop:
   self.orb.compact.toggle_audio();stop.assert_not_called()
  self.assertTrue(self.orb.voice_chat_active);self.assertTrue(nova.config['voice_muted'])
 def test_mute_during_generation_keeps_answer_but_skips_playback(self):
  task=Mock();speech=Mock();self.orb.worker=task;self.orb.voice=speech;self.orb.stream_voice=speech
  self.orb.pending_reply={'route':'test','text':''};self.orb.histories['test']=[]
  self.orb.compact.toggle_audio();self.orb.received(task,'test','Answer')
  speech.finish_input.assert_not_called();speech.cancel.assert_called_once()
  self.assertEqual(self.orb.histories['test'],[{'role':'assistant','content':'Answer'}])
 def test_status_scrolls_to_latest_words(self):
  self.orb.state='Listening';self.orb.live_transcript='hello nova '+('a longer spoken sentence '*20);self.orb.compact.refresh()
  self.assertTrue(self.orb.compact.status.text().startswith('Listening: hello nova'))
  self.assertEqual(self.orb.compact.status.cursorPosition(),len(self.orb.compact.status.text()))
 def test_end_button_stops_session(self):
  self.orb.voice_chat_active=True;self.orb.compact.buttons[4].click()
  self.assertFalse(self.orb.voice_chat_active)
 def test_idle_fade_keeps_orb_interactive(self):
  self.orb.compact.hovered=False;self.orb.compact.fade_idle()
  self.assertTrue(self.orb.compact.buttons[2].isEnabled());self.assertFalse(self.orb.compact.buttons[4].isEnabled())
