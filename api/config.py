"""Local OpenAI-compatible model configuration; never exposed to the browser."""
import os
from urllib.parse import urlsplit
from api.service import ROOT

def configuration():
    values={}
    local=ROOT/'.env.local'
    if local.is_file():
        for line in local.read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key,value=line.split('=',1);values[key.strip()]=value.strip().strip('\"\'')
    for key in ['AIR_AI_BASE_URL','AIR_AI_MODEL','AIR_AI_API_KEY','AIR_AI_TIMEOUT_SECONDS']:
        if key in os.environ:values[key]=os.environ[key]
    base=values.get('AIR_AI_BASE_URL','').rstrip('/');model=values.get('AIR_AI_MODEL','');key=values.get('AIR_AI_API_KEY','')
    url=urlsplit(base)
    valid_url=url.scheme in ('http','https') and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment)
    if url.scheme=='http' and url.hostname not in ('127.0.0.1','localhost','::1'):valid_url=False
    try:timeout=max(1,min(60,float(values.get('AIR_AI_TIMEOUT_SECONDS','40'))))
    except ValueError:timeout=40
    return {'ready':bool(valid_url and model and key),'base_url':base,'model':model,'key':key,'host':url.hostname,'timeout':timeout,'max_tokens':800,'thinking':'disabled' if url.hostname=='api.deepseek.com' else 'provider_default'}
