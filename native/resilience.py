"""Bounded fallback policy; never replay work after output or agent dispatch."""
import time,threading,re
import requests
from behavior_log import event
_LOCK=threading.Lock();_OPEN={}
def available(service):
    with _LOCK:return time.monotonic()>=_OPEN.get(service,0)
def failed(service,error):
    status=getattr(getattr(error,'response',None),'status_code',None)
    with _LOCK:_OPEN[service]=time.monotonic()+(300 if status in (400,401,403) else 45)
    event('fallback_circuit_open',service=service,status=status)
def recovered(service):
    with _LOCK:_OPEN.pop(service,None)
def retryable(error,task):
    if task.cancelled.is_set() or getattr(task,'output_started',False) or getattr(task,'action_started',False):return False
    status=getattr(getattr(error,'response',None),'status_code',None)
    if status:return status==429 or status>=500
    return isinstance(error,(requests.ConnectionError,requests.Timeout)) or bool(re.search(r'HTTP (429|5\d\d)',str(error)))
def model_fallback(task,messages,tools_enabled):
    from model_routes import managed_config,credential
    from agent_backend import chat_with_tools
    if task.cancelled.is_set() or getattr(task,'output_started',False) or getattr(task,'action_started',False):raise RuntimeError('Fallback is unavailable after output or action dispatch.')
    tried={getattr(task,'model',{}).get('provider') if isinstance(getattr(task,'model',None),dict) else None};attempts=0
    local_path=__import__('pathlib').Path.home()/'.nova/desktop.json'
    local_config=__import__('json').loads(local_path.read_text()) if local_path.exists() else {}
    entries=list(managed_config().get('chain',[]))+[{'provider':'ollama','model':local_config.get('ollama_model','tinyllama:latest')}]
    for entry in entries:
        provider=entry.get('provider');model=entry.get('model')
        if provider not in ['groq','nvidia','openrouter','ollama'] or provider in tried or not available('model:'+provider):continue
        tried.add(provider);attempts+=1
        if attempts>3 and provider!='ollama':continue
        try:
            url,key=(local_config.get('ollama_url','http://127.0.0.1:11434').rstrip('/')+'/v1','ollama') if provider=='ollama' else credential(provider);event('model_fallback_started',turn_id=task.turn_id,provider=provider,model=model)
            text=chat_with_tools(task,url,key,model,messages,provider,tools_enabled)
            recovered('model:'+provider);event('model_fallback_completed',turn_id=task.turn_id,provider=provider,model=model)
            return text
        except Exception as error:
            if isinstance(error,(ValueError,KeyError)) and not getattr(task,'action_started',False) and not getattr(task,'output_started',False):
                failed('model:'+provider,error);continue
            if not retryable(error,task):raise
            failed('model:'+provider,error)
    raise RuntimeError('Available fallback models failed. No agent actions were replayed.')
