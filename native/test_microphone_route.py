import unittest
from unittest.mock import patch
import audio_route
class MicrophoneRouteTests(unittest.TestCase):
 def test_manual_finish_without_speech_is_quiet_idle(self):
  from voice_capture import Capture
  from pathlib import Path
  capture=Capture();capture.finish();idle=[];errors=[]
  capture.idle.connect(lambda:idle.append(True));capture.error.connect(errors.append)
  process=__import__('unittest.mock',fromlist=['Mock']).Mock();process.poll.return_value=0
  with patch('voice_capture.subprocess.Popen',return_value=process):capture.run()
  self.assertEqual(idle,[True]);self.assertEqual(errors,[]);self.assertFalse(Path(capture.path).exists())
 def test_default_route_bypasses_silent_echo_filter(self):
  with patch('audio_route.subprocess.check_output',side_effect=['physical-mic\n','physical-speaker\n']),patch('audio_route.subprocess.Popen') as helper:
   self.assertEqual(audio_route.ensure(),('physical-mic','physical-speaker'));helper.assert_not_called()
 def test_capture_uses_selected_device_with_bounded_latency(self):
  command=audio_route.capture_command('physical-mic')
  self.assertIn('--device=physical-mic',command);self.assertIn('--latency-msec=40',command)
if __name__=='__main__':unittest.main()
