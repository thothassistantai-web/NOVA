"""A central, secret-free catalog of NOVA's agent and model adapters."""
import json,shutil
from pathlib import Path
from datetime import datetime,timezone
from model_routes import managed_config
ROOT=Path.home()/'.nova'
def snapshot():
    agents=[]
    for name,command in [('OpenClaw',str(Path.home()/'.local/bin/openclaw')),('Codex',str(Path('/home/nova/NOVA/.tools/node_modules/.bin/codex'))),('Cursor',str(Path.home()/'.local/bin/cursor-agent'))]:
        agents.append({'name':name,'kind':'agent','installed':bool(shutil.which(command)),'adapter':'agent_backend','capabilities':['agent execution','configured tools'],'permissions':'existing backend policy','tool_inventory':'discovered by backend; not assumed shared'})
    counts={}
    for entry in managed_config().get('chain',[]):counts[entry['provider']]=counts.get(entry['provider'],0)+1
    models=[{'name':name,'kind':'model provider','configured_model_count':count,'adapter':'OpenAI-compatible','health':'not probed'} for name,count in counts.items()]
    extensions=ROOT/'integrations.json';future=[]
    if extensions.exists():
        for item in json.loads(extensions.read_text()):
            if isinstance(item,dict) and isinstance(item.get('name'),str):future.append({'name':item['name'],'kind':item.get('kind','external agent'),'health':'registered, adapter required','enabled':False})
    result={'updated_at':datetime.now(timezone.utc).isoformat(),'agents':agents,'model_providers':models,'extensions':future,'shared_context':'confirmed profile + live host facts','cross_agent_history':'not yet unified','secrets':'resolved through existing credential stores; never copied'}
    path=ROOT/'integration-registry.json';path.write_text(json.dumps(result,indent=2)+'\n');path.chmod(0o600)
    return result
