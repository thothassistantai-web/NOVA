import unittest
from unittest.mock import patch
import audio_route
class MicrophoneRouteTests(unittest.TestCase):
 def test_default_route_bypasses_silent_echo_filter(self):
  with patch('audio_route.subprocess.check_output',side_effect=['physical-mic\n','physical-speaker\n']),patch('audio_route.subprocess.Popen') as helper:
   self.assertEqual(audio_route.ensure(),('physical-mic','physical-speaker'));helper.assert_not_called()
 def test_capture_uses_selected_device_with_bounded_latency(self):
  command=audio_route.capture_command('physical-mic')
  self.assertIn('--device=physical-mic',command);self.assertIn('--latency-msec=40',command)
if __name__=='__main__':unittest.main()
