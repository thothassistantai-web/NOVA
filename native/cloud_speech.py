"""Existing Groq speech access, with bounded requests and local fallback."""
import time,requests,wave
from model_routes import credential
from behavior_log import event
from resilience import available,failed,recovered

def transcribe(config,path,cancel=lambda:False):
    from recognizer import transcribe as local
    if config.get('stt_provider','local')=='groq' and available('stt:groq'):
        try:
            if cancel():return None
            url,key=credential('groq');started=time.monotonic()
            with open(path,'rb') as audio:
                response=requests.post(url+'/audio/transcriptions',headers={'Authorization':'Bearer '+key},files={'file':('utterance.wav',audio,'audio/wav')},data={'model':'whisper-large-v3-turbo','language':'en','response_format':'json'},timeout=(3,12))
            response.raise_for_status()
            if cancel():return None
            text=response.json()['text'].strip()
            recovered('stt:groq')
            event('cloud_transcription_completed',provider='groq',seconds=round(time.monotonic()-started,3))
            return text
        except Exception as error:
            if cancel():return None
            failed('stt:groq',error)
            event('cloud_transcription_fallback',provider='groq',error=type(error).__name__)
    if config.get('partial_request'):return None
    return local(config,path,cancel)

def synthesize(text,path,config,cancel=lambda:False):
    if config.get('tts_provider')!='groq' or not available('tts:groq'):return False
    try:
        if cancel():return False
        url,key=credential('groq');started=time.monotonic()
        response=requests.post(url+'/audio/speech',headers={'Authorization':'Bearer '+key},json={'model':'canopylabs/orpheus-v1-english','voice':config.get('groq_voice','hannah'),'input':text,'response_format':'wav'},timeout=(3,15))
        response.raise_for_status()
        if cancel():return False
        import io,numpy as np
        with wave.open(io.BytesIO(response.content),'rb') as source:
            params=source.getparams();raw=source.readframes(source.getnframes())
        if params.sampwidth!=2:raise ValueError('Unexpected speech sample format')
        from audio_quality import gain_pcm
        boosted=gain_pcm(raw,config.get('tts_volume_percent',175)/100)
        with wave.open(str(path),'wb') as output:
            output.setparams(params);output.writeframes(boosted)
        recovered('tts:groq')
        event('cloud_voice_ready',provider='groq',seconds=round(time.monotonic()-started,3));return True
    except Exception as error:
        if not cancel():failed('tts:groq',error);event('cloud_voice_fallback',provider='groq',error=type(error).__name__)
        return False
