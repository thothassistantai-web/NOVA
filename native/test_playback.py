import unittest,tempfile,threading,wave
from pathlib import Path
from unittest.mock import patch,Mock
from speech_output import StreamSpeech
class PlaybackTests(unittest.TestCase):
 def test_boost_has_no_hard_clipping(self):
  from audio_quality import gain_pcm
  import array
  source=array.array('h',[0,8000,16000,25000,32767,-32768])
  output=array.array('h');output.frombytes(gain_pcm(source.tobytes(),1.75))
  self.assertGreater(output[1],source[1]);self.assertLess(max(output),32767);self.assertGreater(min(output),-32768)
 def test_buffered_reply_keeps_file_until_playback_and_finishes(self):
  speech=StreamSpeech({'tts_model':'test','tts_volume_percent':175});speech.add_text('First sentence. ');speech.add_text('Second sentence.');speech.finish_input();seen=[]
  def generate(text,path,*args):
   seen.append(text)
   with wave.open(path,'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*1600)
  process=Mock();process.returncode=0
  def play(command,**kwargs):self.assertTrue(Path(command[-1]).exists());seen.append(command[-1]);return process
  with patch('speech_output.generate_wav',side_effect=generate),patch('speech_output.subprocess.Popen',side_effect=play):speech.run()
  self.assertEqual(seen[0],'First sentence. Second sentence.');self.assertEqual(speech.spoken_text,seen[0]);self.assertFalse(Path(seen[1]).exists());self.assertEqual(speech.partial_text,'')
 def test_cancel_discards_buffer_without_playback(self):
  speech=StreamSpeech({'tts_model':'test'});speech.add_text('Do not play');speech.cancel()
  with patch('speech_output.generate_wav') as generate:speech.run();generate.assert_not_called()
if __name__=='__main__':unittest.main()
