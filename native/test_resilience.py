import unittest,threading
from types import SimpleNamespace
from unittest.mock import patch
import requests,resilience
class ResilienceTests(unittest.TestCase):
 def setUp(self):resilience._OPEN.clear();self.task=SimpleNamespace(cancelled=threading.Event(),output_started=False,action_started=False)
 def test_provider_fallback_reaches_local_after_cloud_failures(self):
  self.task.turn_id='test';self.task.model={'provider':'original'}
  chain=[{'provider':'groq','model':'one'},{'provider':'nvidia','model':'two'},{'provider':'openrouter','model':'three'}]
  with patch('model_routes.managed_config',return_value={'chain':chain}),patch('model_routes.credential',return_value=('http://test','key')),patch('agent_backend.chat_with_tools',side_effect=[requests.Timeout(),requests.Timeout(),requests.Timeout(),'Offline answer']) as chat:
   self.assertEqual(resilience.model_fallback(self.task,[],False),'Offline answer')
   self.assertEqual(chat.call_count,4);self.assertEqual(chat.call_args.args[5],'ollama')
 def test_network_failure_can_fail_over(self):self.assertTrue(resilience.retryable(requests.Timeout(),self.task))
 def test_partial_answer_never_replays(self):
  self.task.output_started=True;self.assertFalse(resilience.retryable(requests.Timeout(),self.task))
 def test_dispatched_action_never_replays(self):
  self.task.action_started=True;self.assertFalse(resilience.retryable(requests.Timeout(),self.task))
 def test_permission_denial_never_replays(self):
  response=requests.Response();response.status_code=403
  self.assertFalse(resilience.retryable(requests.HTTPError(response=response),self.task))
 def test_cancellation_never_replays(self):
  self.task.cancelled.set();self.assertFalse(resilience.retryable(requests.Timeout(),self.task))
 def test_circuit_skips_repeated_failure_then_recovers(self):
  resilience.failed('tts:groq',requests.Timeout());self.assertFalse(resilience.available('tts:groq'));resilience.recovered('tts:groq');self.assertTrue(resilience.available('tts:groq'))
if __name__=='__main__':unittest.main()
