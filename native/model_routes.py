"""Read Cursor's managed model catalog and credentials without altering Cursor."""
import importlib.util
import json
from pathlib import Path
import requests

ROOT=Path.home()/'.cursor/cursor-fallback'
CACHE=Path.home()/'.nova/router-models.json'
LABELS={'9router':'9router','NVIDIA':'nvidia','OpenRouter':'openrouter','Groq':'groq',
        'Gemini':'gemini','Mistral':'mistral','Ollama Cloud':'ollama_cloud','Wiro':'wiro',
        'GitHub Models':'github_models'}

def managed_config():
    p=ROOT/'config.json'
    return json.loads(p.read_text()) if p.exists() else {'providers':{},'chain':[]}

def credential(provider):
    cfg=managed_config().get('providers',{}).get(provider,{})
    if not cfg.get('base_url'): raise ValueError('Provider endpoint is not configured: '+provider)
    spec=importlib.util.spec_from_file_location('nova_shared_credentials',ROOT/'secrets.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    key,_=module.resolve_api_key(cfg.get('api_key_env',''))
    if not key and provider!='ollama':raise ValueError('No configured credential for '+provider)
    return cfg['base_url'].rstrip('/'),key

def catalogs(local_config):
    cfg=managed_config(); chain=cfg.get('chain',[])
    result={'OpenClaw':[], 'Codex Agent':[], 'Cursor Agent':[], 'Managed Free Models':[dict(x) for x in chain], '9router':[]}
    if CACHE.exists():result['9router']=json.loads(CACHE.read_text())
    for label,provider in LABELS.items():
        if label=='9router':continue
        entries=[dict(x) for x in chain if x.get('provider')==provider]
        if entries:result[label]=entries
    local_cache=Path.home()/'.nova/ollama-models.json'
    result['Ollama']=json.loads(local_cache.read_text()) if local_cache.exists() else [{'provider':'ollama','model':local_config['ollama_model']}]
    result['OpenAI API']=[{'provider':'openai','model':local_config['openai_model']}]
    result['Claude API']=[{'provider':'anthropic','model':local_config['claude_model']}]
    return result

def refresh_router():
    url,key=credential('9router')
    r=requests.get(url+'/models',headers={'Authorization':'Bearer '+key},timeout=(5,20));r.raise_for_status()
    entries=[{'provider':'9router','model':x['id'],'display_name':x.get('name',x['id'])}
             for x in r.json().get('data',[]) if x.get('id')]
    if not entries:raise ValueError('9router returned an empty model catalog')
    CACHE.write_text(json.dumps(entries,indent=2)+'\n')
    return entries

def route_key(provider,entry):
    return provider if not entry else f"{entry['provider']} / {entry['model']}"
