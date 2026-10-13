"""Fresh host facts supplied independently of model training data."""
import json,re,platform
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
PROFILE=Path.home()/'.nova/profile.json'

def profile():
    return json.loads(PROFILE.read_text()) if PROFILE.exists() else {'timezone':'America/New_York','location':'Unknown'}

def facts():
    p=profile();now=datetime.now(ZoneInfo(p['timezone']))
    return {'current_time':now.isoformat(),'timezone':p['timezone'],'location':p.get('location','Unknown'),
      'location_source':p.get('location_source','not provided'),'location_is_live_gps':False,
      'user':p.get('name','Damian'),'operating_system':platform.platform(),
      'assistant_agent':'nova-desktop','openclaw_workspace':'/home/nova/openclaw/workspace',
      'capability_note':'OpenClaw agents have their configured tools, browser and plugin bridges. Direct models can request run_system_agent. Tool access/authentication must be checked; do not claim completion without evidence.'}

def prompt():
    return ('You are NOVA, Damian\'s desktop voice and text assistant. Answer naturally and concisely, suitable for speaking. '
      'The following fresh host facts are authoritative; you CAN know the current time and saved location. '
      'Saved location is city-level, not live GPS. Use tools for internet and computer actions. '
      'Never claim actions or access succeeded without actual tool results. Discover installed tools/skills when needed. '
      'Preserve existing permissions and do not contact other people without explicit user instructions. '
      'Do not read or expose credentials. Host facts: '+json.dumps(facts(),ensure_ascii=False))

def local_answer(text):
    q=text.lower().strip(' .?!');q=re.sub(r"\b(please|nova|hey|hello)\b",'',q).strip()
    wants_time=bool(re.fullmatch(r"(?:what(?:'s| is)?|tell me|give me)?\s*(?:the )?(?:current |local )?time(?: is it| now)?",q))
    wants_location=bool(re.fullmatch(r"(?:where am i|what(?:'s| is) my location|what city am i in|where am i located|where do i live)",q))
    combined=q in {'time and location','what is the time and my location','what time is it and where am i'}
    if not(wants_time or wants_location or combined):return None
    p=profile();now=datetime.now(ZoneInfo(p['timezone']));parts=[]
    if wants_time or combined:parts.append('It is '+now.strftime('%I:%M %p %Z on %A, %B %d').lstrip('0')+'.')
    if wants_location or combined:parts.append('Your saved location is '+p.get('location','not set')+'. This is your confirmed location, not a live GPS reading.')
    return ' '.join(parts)
