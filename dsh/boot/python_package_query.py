"""Bounded npm-compatible metadata reads for the native Python package backend.

This reads manifests only; publishing JavaScript on a registry never makes its
runtime code executable by the Python host.
"""
import base64
import json
import os
import re
import time
from http.client import HTTPException
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlsplit,urlunsplit,unquote
from urllib.request import Request,HTTPRedirectHandler

from dsh.boot.plugin_install_spec import parse_install_spec
from dsh.boot.plugin_registry_policy import normalize_registry,OFFICIAL_NPM_REGISTRY,UNSPECIFIED
from dsh.boot.semver import parse,satisfies
from dsh.host.http_proxy import build_opener

MAX_METADATA_BYTES=8*1024*1024


class PackageQueryError(ValueError):
    def __init__(self,code,message):
        self.code=code;self.message=message
        super().__init__(code+' '+message)


def npm_configuration(directory,env=None):
    env=os.environ if env is None else env
    home=env.get('USERPROFILE') or env.get('HOME') or ''
    user=env.get('NPM_CONFIG_USERCONFIG',env.get('npm_config_userconfig',os.path.join(home,'.npmrc')))
    values={}
    for path in [user,os.path.join(directory,'.npmrc')]:
        if not path:continue
        try:
            with open(path,encoding='utf-8-sig') as stream:text=stream.read()
        except FileNotFoundError:continue
        for line in text.splitlines():
            line=line.strip()
            if not line or line[0] in '#;' or '=' not in line:continue
            key,value=line.split('=',1);value=value.strip()
            if len(value)>1 and value[0]==value[-1] and value[0] in '\"\'':value=value[1:-1]
            values[key.strip()]=re.sub(r'\$\{([^}]+)\}',lambda match:env.get(match[1],match[0]),value)
    for key,value in env.items():
        if key.lower().startswith('npm_config_'):values[key[11:].lower()]=value
    return values


def configured_registry(configuration):
    return normalize_registry(configuration.get('registry',OFFICIAL_NPM_REGISTRY))


def _public(url):
    fields=urlsplit(url);host=fields.netloc.rsplit('@',1)[-1]
    return urlunsplit((fields.scheme,host,fields.path,'',''))


def _registry_request(registry,name,configuration):
    fields=urlsplit(normalize_registry(registry));authority=fields.netloc.rsplit('@',1)[-1]
    url=urlunsplit((fields.scheme,authority,fields.path+quote(name,safe='@'),fields.query,''))
    headers={'Accept':'application/json','Accept-Encoding':'identity','User-Agent':'dsh-python-package/1'}
    # Authentication belongs to a configured registry prefix, never a mirror.
    credentials=[]
    for key,value in configuration.items():
        if not key.startswith('//') or ':' not in key:continue
        prefix,kind=key.rsplit(':',1)
        if kind not in ('_authToken','_auth'):continue
        expected=fields.scheme+':'+prefix.rstrip('/')+'/'
        if url.startswith(expected):credentials.append((len(prefix),kind,value))
    if credentials:
        _,kind,value=max(credentials,key=lambda row:row[0])
        headers['Authorization']=('Bearer ' if kind=='_authToken' else 'Basic ')+value
    elif fields.username is not None:
        value=unquote(fields.username)+':'+unquote(fields.password or '')
        headers['Authorization']='Basic '+base64.b64encode(value.encode('utf-8')).decode('ascii')
    return Request(url,headers=headers)


class RegistryRedirects(HTTPRedirectHandler):
    max_redirections=5
    def redirect_request(self,request,response,code,message,headers,url):
        target=urlsplit(url);origin=urlsplit(request.full_url)
        if target.scheme not in ('http','https') or target.username is not None or target.password is not None:
            raise PackageQueryError('ERR_PNPM_META_FETCH_FAIL','invalid registry redirect')
        if origin.scheme=='https' and target.scheme!='https':
            raise PackageQueryError('ERR_PNPM_META_FETCH_FAIL','registry redirect downgrades HTTPS')
        redirected=super().redirect_request(request,response,code,message,headers,url)
        if redirected is not None:
            # A redirected resource is not the configured authentication prefix.
            redirected.remove_header('Authorization')
        return redirected


def read_packument(name,registry,configuration=None,timeout_ms=15000,max_bytes=MAX_METADATA_BYTES):
    if type(max_bytes) is not int or max_bytes<1 or not isinstance(timeout_ms,(int,float)) or not 0<timeout_ms<float('inf'):
        raise ValueError('metadata limits must be positive and finite')
    configuration=configuration or {};request=_registry_request(registry,name,configuration)
    public=_public(request.full_url);deadline=time.monotonic()+timeout_ms/1000
    try:
        with build_opener(RegistryRedirects()).open(request,timeout=max(.001,timeout_ms/1000)) as response:
            if response.getcode()!=200:raise PackageQueryError('ERR_PNPM_META_FETCH_FAIL','GET '+public+': incomplete response')
            if response.headers.get('Content-Encoding','identity').lower()!='identity':
                raise PackageQueryError('ERR_PNPM_META_FETCH_FAIL','GET '+public+': encoded metadata is unsupported')
            length=response.headers.get('Content-Length')
            if length is not None and (not re.fullmatch(r'[0-9]+',length.strip()) or int(length)>max_bytes):
                raise PackageQueryError('ERR_PNPM_META_FETCH_FAIL','GET '+public+': metadata exceeds byte limit')
            chunks=[];size=0
            while True:
                if time.monotonic()>=deadline:raise PackageQueryError('ERR_PNPM_META_FETCH_FAIL','GET '+public+': ETIMEDOUT')
                chunk=response.read1(min(65536,max_bytes-size+1))
                if not chunk:break
                chunks.append(chunk);size+=len(chunk)
                if size>max_bytes:raise PackageQueryError('ERR_PNPM_META_FETCH_FAIL','GET '+public+': metadata exceeds byte limit')
            if length is not None and size!=int(length):raise PackageQueryError('ERR_PNPM_META_FETCH_FAIL','GET '+public+': incomplete metadata')
        def reject(value):raise ValueError('invalid JSON constant')
        value=json.loads(b''.join(chunks).decode('utf-8'),parse_constant=reject)
        if not isinstance(value,dict):raise ValueError('registry metadata must be an object')
        return value
    except HTTPError as error:
        raise PackageQueryError('ERR_PNPM_FETCH_'+str(error.code),'GET '+public+': '+str(error.code)) from None
    except PackageQueryError:raise
    except (URLError,OSError,ValueError,UnicodeError,HTTPException) as error:
        raise PackageQueryError('ERR_PNPM_META_FETCH_FAIL','GET '+public+': '+type(error).__name__) from None


def query_metadata(directory,spec,fields,registry=None,env=None,**limits):
    parsed=parse_install_spec(spec)
    if parsed['kind']!='registry':raise PackageQueryError('ERR_PNPM_SPEC_NOT_SUPPORTED_BY_ANY_RESOLVER','metadata requires a registry package')
    if parsed.get('range','').startswith('npm:'):
        parsed=parse_install_spec(parsed['range'][4:])
        if parsed['kind']!='registry':raise PackageQueryError('ERR_PNPM_SPEC_NOT_SUPPORTED_BY_ANY_RESOLVER','metadata alias requires a registry package')
    configuration=npm_configuration(directory,env);name=parsed['name'];selected=registry or configured_registry(configuration)
    if name.startswith('@'):selected=configuration.get(name.split('/',1)[0]+':registry',selected)
    document=read_packument(name,selected,configuration,**limits)
    versions=document.get('versions') or {};tags=document.get('dist-tags') or {}
    if not versions:raise PackageQueryError('ERR_PNPM_NO_VERSIONS','No versions available for '+name)
    wanted=parsed.get('range') or 'latest';wanted=tags.get(wanted,wanted)
    try:exact=parse(wanted).canonical()
    except ValueError:exact=None
    if exact is not None:chosen=[versions[wanted]] if wanted in versions else []
    else:
        chosen=[]
        for version,manifest in versions.items():
            try:accepted=satisfies(version,wanted,include_prerelease=False)
            except (ValueError,TypeError):accepted=False
            if accepted:chosen.append(manifest)
        chosen.sort(key=lambda manifest:parse(manifest['version']))
        latest=tags.get('latest');preferred=versions.get(latest)
        if preferred is not None and (wanted=='*' or satisfies(latest,wanted,include_prerelease=False)):
            if not preferred.get('deprecated'):chosen=[preferred]
            else:
                stable=[manifest for manifest in chosen if not manifest.get('deprecated')]
                chosen=stable[-1:] or [preferred]
        elif chosen:
            stable=[manifest for manifest in chosen if not manifest.get('deprecated')]
            chosen=stable[-1:] or chosen[-1:]
    if not chosen:raise PackageQueryError('ERR_PNPM_PACKAGE_NOT_FOUND','No matching version for '+name+'@'+wanted)
    info=dict(chosen[-1],versions=list(versions),**{'dist-tags':tags})
    times=document.get('time')
    if isinstance(times,dict) and all(times.get(version) for version in versions):info['time']=times
    def field(path):
        value=info
        for part in path.split('.'):
            if not isinstance(value,dict) or part not in value:return UNSPECIFIED
            value=value[part]
        return value
    if len(fields)==1:return field(fields[0])
    return {key:field(key) for key in fields if field(key) is not UNSPECIFIED}
