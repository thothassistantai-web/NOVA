import unittest,tempfile
from unittest.mock import Mock,patch
from pathlib import Path
import cloud_speech
class CloudSpeechTests(unittest.TestCase):
 def setUp(self):
  from resilience import _OPEN
  _OPEN.clear()
 def test_cloud_transcription_success_uses_existing_credentials(self):
  response=Mock();response.json.return_value={'text':' Hello Nova. '}
  with tempfile.NamedTemporaryFile() as audio,patch('cloud_speech.credential',return_value=('http://test','existing-key')),patch('cloud_speech.requests.post',return_value=response) as post:
   self.assertEqual(cloud_speech.transcribe({'stt_provider':'groq'},audio.name),'Hello Nova.')
   self.assertEqual(post.call_args.kwargs['data']['model'],'whisper-large-v3-turbo')
 def test_failure_falls_back_locally(self):
  with patch('cloud_speech.credential',side_effect=ValueError('Unavailable')),patch('recognizer.transcribe',return_value='Local result') as local:
   self.assertEqual(cloud_speech.transcribe({'stt_provider':'groq'},'test.wav'),'Local result');local.assert_called_once()
 def test_cancelled_cloud_result_never_falls_back_or_returns_text(self):
  response=Mock();response.json.return_value={'text':'Stale'}
  with tempfile.NamedTemporaryFile() as audio,patch('cloud_speech.credential',return_value=('http://test','key')),patch('cloud_speech.requests.post',return_value=response),patch('recognizer.transcribe') as local:
   self.assertIsNone(cloud_speech.transcribe({'stt_provider':'groq'},audio.name,Mock(side_effect=[False,True])));local.assert_not_called()
 def test_voice_terms_failure_uses_local_fallback(self):
  with patch('cloud_speech.credential',side_effect=ValueError('Terms required')):
   self.assertFalse(cloud_speech.synthesize('Test','test.wav',{'tts_provider':'groq'}))
if __name__=='__main__':unittest.main()
