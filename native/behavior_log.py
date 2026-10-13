"""Private rotating behavior events for troubleshooting and improvement."""
import json, logging, os, re
from datetime import datetime,timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
ROOT=Path.home()/'.nova/logs';ROOT.mkdir(parents=True,exist_ok=True)
log=logging.getLogger('nova.behavior');log.setLevel(logging.INFO);log.propagate=False
if not log.handlers:
    handler=RotatingFileHandler(ROOT/'behavior.jsonl',maxBytes=5_000_000,backupCount=4,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'));log.addHandler(handler)
    (ROOT/'behavior.jsonl').chmod(0o600)

def clean(value):
    if isinstance(value,str):
        value=re.sub(r'(?i)(bearer\s+)[\w.\-]+',r'\1[REDACTED]',value)
        value=re.sub(r'\b(?:sk-|gsk_|nvapi-)[A-Za-z0-9_\-]{12,}', '[REDACTED]', value)
        value=re.sub(r'(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+',r'\1[REDACTED]',value)
        return value[:20000]
    if isinstance(value,dict):return {k:('[REDACTED]' if any(x in k.lower() for x in ['api_key','password','authorization','secret','token']) else clean(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    return value

def event(name,**fields):
    if os.environ.get('NOVA_TESTING')=='1':return
    log.info(json.dumps(clean({'timestamp':datetime.now(timezone.utc).isoformat(),'event':name,**fields}),ensure_ascii=False))
    for path in ROOT.glob('behavior.jsonl*'):
        try:path.chmod(0o600)
        except OSError:pass

def runtime(state,route,**activity):
    if os.environ.get('NOVA_TESTING')=='1':return
    p=Path.home()/'.nova/runtime.json';tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps({'pid':os.getpid(),'state':state,'route':route,'updated_at':datetime.now(timezone.utc).isoformat(),**activity}));tmp.chmod(0o600);tmp.replace(p)
