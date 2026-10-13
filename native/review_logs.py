#!/usr/bin/python3
"""Incremental behavior review. Reports evidence; never edits app code automatically."""
import json,os,statistics
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path.home()/'.nova/logs';STATE=ROOT/'monitor-state.json';REPORT=ROOT/'health-review.json'
def review():
    now=datetime.now(timezone.utc)
    last=json.loads(STATE.read_text()).get('last_review') if STATE.exists() else None
    since=datetime.fromisoformat(last) if last else now-timedelta(hours=24)
    events=[]
    for p in ROOT.glob('behavior.jsonl*'):
        for line in p.read_text(errors='replace').splitlines():
            try:
                e=json.loads(line)
                if datetime.fromisoformat(e['timestamp'])>since:events.append(e)
            except (ValueError,KeyError):pass
    events.sort(key=lambda x:x['timestamp'])
    failures=[e for e in events if e['event'] in ['request_failed','tts_failed','interaction_failed']]
    completed=[e for e in events if e['event']=='request_completed']
    recovered=[e for e in failures if e['event']=='request_failed' and any(x.get('route')==e.get('route') and x['timestamp']>e['timestamp'] for x in completed)]
    unresolved=[e for e in failures if e not in recovered]
    slow=[e for e in completed if e.get('duration_seconds',0)>45]
    slow_recognition=[e for e in events if e.get('event')=='transcription_latency' and e.get('seconds',0)>10]
    runtime_path=Path.home()/'.nova/runtime.json';runtime=json.loads(runtime_path.read_text()) if runtime_path.exists() else {}
    running=False
    if runtime.get('pid'):
        try:running='native/nova.py' in Path(f"/proc/{runtime['pid']}/cmdline").read_text();
        except OSError:pass
    age=(now-datetime.fromisoformat(runtime['updated_at'])).total_seconds() if runtime.get('updated_at') else None
    actionable=[]
    if not running:actionable.append('NOVA desktop process is not running.')
    if unresolved:actionable.append(f'{len(unresolved)} new unresolved interaction/request/voice failures. Inspect the events for root causes.')
    if slow_recognition:actionable.append(f'{len(slow_recognition)} transcriptions exceeded ten seconds; inspect local recognition load.')
    if slow:actionable.append(f'{len(slow)} completed requests exceeded 45 seconds.')
    if running and not (runtime.get('state') in ['Ready','Listening'] and runtime.get('continuous_voice_session')) and runtime.get('state') not in ['Idle','Error'] and age and age>240:actionable.append('NOVA has remained in an active state for over four minutes; verify it is not stuck.')
    result={'reviewed_at':now.isoformat(),'since':since.isoformat(),'running':running,'runtime':runtime,
      'new_events':len(events),'completed_requests':len(completed),'failures':unresolved,'recovered_failures':recovered,'slow_requests':slow,'slow_transcriptions':slow_recognition,
      'actionable':actionable,'safe_to_restart':running and runtime.get('state') in ['Idle','Error'] and not any(runtime.get(k) for k in ['continuous_voice_session','microphone_active','request_pending','speech_active','barge_monitor_active','listen_pending'])}
    for path,data in [(REPORT,result),(STATE,{'last_review':now.isoformat()})]:
        path.write_text(json.dumps(data,indent=2)+'\n');path.chmod(0o600)
    print(json.dumps(result,indent=2))
    return result
if __name__=='__main__':review()
