"""Agent bridges and a small tool loop for OpenAI-compatible model routes."""
import json,os,tempfile,time
from pathlib import Path
import requests
from behavior_log import event
from system_context import prompt,facts

TOOLS=[{'type':'function','function':{'name':'get_system_context','description':'Get the actual current clock, confirmed saved location and desktop environment.','parameters':{'type':'object','properties':{},'additionalProperties':False}}},
 {'type':'function','function':{'name':'run_system_agent','description':'Ask an installed agent to carry out the user\'s requested task with its configured computer, shell, browser, internet, MCP, plugin and skill tools. Use for tasks needing live information, files or desktop actions. Existing agent permissions still apply.','parameters':{'type':'object','properties':{'request':{'type':'string'},'backend':{'type':'string','enum':['OpenClaw','Codex','Cursor']}},'required':['request'],'additionalProperties':False}}}]

def run_agent(task,backend,request,session):
    task.action_started=True
    import subprocess
    fd,out_path=tempfile.mkstemp(prefix='nova-agent-',suffix='.txt');os.close(fd)
    message=prompt()+'\n\nUser request:\n'+request
    try:
        if backend=='OpenClaw':
            command=[str(Path.home()/'.local/bin/openclaw'),'agent','--agent','nova-desktop',
              '--session-id',session,'--message-file',out_path,'--json','--timeout','180']
            Path(out_path).write_text(message);stdin=None
        elif backend=='Codex':
            command=[str(Path('/home/nova/NOVA/.tools/node_modules/.bin/codex')),'exec','--skip-git-repo-check','-C',str(Path.home()),'--output-last-message',out_path,'-'];stdin=message
        elif backend=='Cursor':
            command=[str(Path.home()/'.local/bin/cursor-agent'),'--print','--output-format','json','--workspace',str(Path.home()),message];stdin=None
        else:raise ValueError('Unknown agent backend')
        event('agent_started',turn_id=task.turn_id,backend=backend,session=session)
        task.process=subprocess.Popen(command,stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        out,err=task.process.communicate(input=stdin,timeout=200)
        if task.cancelled.is_set():return ''
        if task.process.returncode:raise RuntimeError(backend+' agent failed: '+err[-700:])
        if backend=='Codex':answer=Path(out_path).read_text().strip()
        elif backend=='Cursor':
            data=json.loads(out[out.find('{'):]);answer=data.get('result') or data.get('text') or ''
            if not isinstance(answer,str):answer=json.dumps(answer)
        else:
            data=json.loads(out[out.find('{'):]);root=data.get('result',data)
            answer='\n'.join(x.get('text','') for x in root.get('payloads',[]) if x.get('text'))
            meta=root.get('meta',{});report=meta.get('systemPromptReport',{})
            names=[x.get('name') for x in report.get('tools',{}).get('entries',[]) if x.get('name')]
            event('agent_capabilities',turn_id=task.turn_id,backend=backend,tools=names,model=meta.get('agentMeta',{}).get('model'))
            event('agent_tool_summary',turn_id=task.turn_id,summary=meta.get('toolSummary',{}),execution_trace=meta.get('executionTrace',{}))
        if not answer:raise RuntimeError(backend+' returned no answer text.')
        event('agent_completed',turn_id=task.turn_id,backend=backend)
        return answer
    finally:Path(out_path).unlink(missing_ok=True)

def request_message(task,url,key,model,messages,tools_enabled=True,provider=''):
    body={'model':model,'messages':messages,'max_tokens':2048,'stream':True}
    if tools_enabled:body['tools']=TOOLS;body['tool_choice']='auto'
    if provider=='openrouter':body['provider']={'max_price':{'prompt':0,'completion':0}}
    task.response=requests.post(url.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','User-Agent':'NOVA-Desktop/0.4'},json=body,stream=True,timeout=(5,180))
    if not task.response.ok:raise RuntimeError(f'{provider or model}: HTTP {task.response.status_code}. Check availability or tool support; choose OpenClaw for system tasks.')
    if 'text/event-stream' not in task.response.headers.get('Content-Type',''):
        data=task.response.json()
        return data.get('choices',[{}])[0].get('message',{})
    parts=[];calls={}
    for line in task.response.iter_lines():
        if task.cancelled.is_set():return {}
        if not line or not line.startswith(b'data:'):continue
        raw=line[5:].strip()
        if raw==b'[DONE]':break
        data=json.loads(raw)
        if data.get('error'):raise RuntimeError('Provider generation failed')
        for choice in data.get('choices',[]):
            delta=choice.get('delta',{});text=delta.get('content')
            if isinstance(text,str):
                parts.append(text)
                task.output_started=True
                if hasattr(task,'delta'):task.delta.emit(text)
            for tc in delta.get('tool_calls',[]):
                entry=calls.setdefault(tc.get('index',0),{'id':'','type':'function','function':{'name':'','arguments':''}})
                if tc.get('id'):entry['id']=tc['id']
                fn=tc.get('function',{})
                entry['function']['name']+=fn.get('name','');entry['function']['arguments']+=fn.get('arguments','')
    result={'role':'assistant','content':''.join(parts)}
    if calls:result['tool_calls']=list(calls.values())
    return result

def chat_with_tools(task,url,key,model,messages,provider='',tools_enabled=True):
    work=[dict(x) for x in messages]
    for step in range(5):
        answer=request_message(task,url,key,model,work,tools_enabled,provider)
        if task.cancelled.is_set():return ''
        calls=answer.get('tool_calls',[])
        if not calls:
            text=answer.get('content','')
            if not text:raise RuntimeError('No answer text returned. Try another model.')
            return text
        work.append(answer)
        for call in calls:
            task.action_started=True
            fn=call['function'];name=fn['name'];args=json.loads(fn.get('arguments') or '{}')
            event('tool_started',turn_id=task.turn_id,tool=name,arguments=args)
            try:
                if name=='get_system_context':result=json.dumps(facts())
                elif name=='run_system_agent':result=run_agent(task,args.get('backend','OpenClaw'),args['request'],task.session)
                else:raise ValueError('Unknown tool: '+name)
            except Exception as e:result='Tool failed: '+str(e)
            if task.cancelled.is_set():return ''
            event('tool_completed',turn_id=task.turn_id,tool=name,result=result)
            work.append({'role':'tool','tool_call_id':call['id'],'content':result})
    raise RuntimeError('Tool step limit reached; choose OpenClaw for this task.')
