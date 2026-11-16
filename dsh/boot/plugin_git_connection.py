"""Bounded read-only Git preflight using the owned subprocess provider."""
import os
import re
import tempfile
from urllib.parse import urlsplit, quote, unquote

from dsh.boot.plugin_install_spec import classify_install_failure, _url_host
from dsh.boot.plugin_package_view import _execute_package_query


def _hosted(url, original):
    host = url.hostname or ''
    if host.startswith('www.'):host = host[4:]
    protocol = original.split(':', 1)[0].lower()+':'
    allowed = {'github.com':('http:', 'https:', 'git+https:'),
        'bitbucket.org':('https:', 'git+https:'), 'gitlab.com':('https:', 'git+https:'),
        'gist.github.com':('https:', 'git+https:'), 'git.sr.ht':('https:',)}
    if protocol not in allowed.get(host, ()):return False
    parts = url.path.split('/')
    user = parts[1] if len(parts)>1 else ''
    project = parts[2] if len(parts)>2 else ''
    aux = parts[3] if len(parts)>3 else ''
    if project.endswith('.git'):project = project[:-4]
    if host == 'github.com':valid = bool(user and project and aux in ('', 'tree'))
    elif host == 'gitlab.com':
        user='/'.join(parts[1:-1]);project=parts[-1][:-4] if parts[-1].endswith('.git') else parts[-1]
        valid = bool(user and project and '/-/' not in url.path and '/archive.tar.gz' not in url.path)
    elif host == 'gist.github.com':valid = bool((project or user) and aux != 'raw')
    elif host == 'git.sr.ht':valid = bool(user and project and aux != 'archive')
    else:valid = bool(user and project and aux != 'get')
    if not valid:return False
    try:
        for value in (user, project, url.fragment):
            if re.search(r'%(?![0-9a-fA-F]{2})', value):return False
            unquote(value, encoding='utf-8', errors='strict')
    except UnicodeDecodeError:return False
    return True


def ssh_git_spec(spec):
    text = spec['spec']
    if spec['kind'] != 'git' or not re.match(r'^(?:git\+)?https?://', text, re.I):return None
    raw = re.sub(r'^git\+', '', text, flags=re.I)
    boundary = min([raw.find(char) for char in '?#' if char in raw] or [len(raw)])
    raw = raw[:boundary].replace('\\', '/')+raw[boundary:]
    # The install parser has already validated the URL. Serialize its path as
    # WHATWG does, preserving the source fragment byte spelling separately.
    url = urlsplit(raw)
    authority = _url_host(raw)
    host = authority[:authority.index(']')+1] if authority.startswith('[') else authority.split(':',1)[0]
    path = quote(url.path, safe=''.join(chr(code) for code in range(33,127) if chr(code) not in '"#<>?`{}')) or '/'
    segments=[]
    for index, segment in enumerate(path.split('/')):
        dot=re.sub('%2e', '.', segment, flags=re.I)
        if dot == '.':
            if index==len(path.split('/'))-1:segments.append('')
        elif dot == '..':
            if len(segments)>1:segments.pop()
            if index==len(path.split('/'))-1:segments.append('')
        else:segments.append(segment)
    path = '/'.join(segments)
    if _hosted(url._replace(path=path), text) or url.username or url.password or url.query:return None
    fragment = '#'+text.split('#',1)[1] if '#' in text else ''
    return 'git+ssh://git@'+host+path+fragment


async def choose_git_transport(spec, directory, options):
    ssh = ssh_git_spec(spec)
    if ssh is None:return spec['spec']
    def strip(value):return re.sub(r'^git\+', '', value, flags=re.I).split('#',1)[0]
    async def readable(repository):
        env = dict(options.get('env') or {}, LC_ALL='C', GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never',
            GIT_ASKPASS='', SSH_ASKPASS='', SSH_ASKPASS_REQUIRE='never')
        result = await _execute_package_query(directory, ['git','-c','core.askPass=','ls-remote','--exit-code','--',repository,'HEAD'],
            dict(options,env=env,_discardOutput=True))
        return result['exitCode'] == 0 and not result.get('cause') and not result['timedOut']
    if await readable(strip(spec['spec'])):return spec['spec']
    if options['signal'].aborted or not await readable(strip(ssh)):return spec['spec']
    return ssh


async def check_github_connection(spec, directory, options):
    if spec['kind'] != 'git':return None
    host = re.sub(':.*$', '', spec['host'].lower())
    if host != 'github.com' and not host.endswith('.github.com'):return None
    return await check_git_connection(spec, directory, options)


async def check_git_connection(spec, directory, options):
    repository = spec['spec'].split('#',1)[0]
    repository = re.sub(r'^(?:github|gitlab|bitbucket|gist):', lambda _:'https://'+spec['host']+'/', repository, flags=re.I)
    repository = re.sub(r'^git\+', '', repository, flags=re.I)
    log_root = os.path.join(directory, '.plugin-manager', 'logs')
    os.makedirs(log_root, mode=0o700, exist_ok=True)
    log_directory = tempfile.mkdtemp(prefix='github-connection-', dir=log_root)
    log_path = os.path.join(log_directory, 'git.log')
    argv = ['git','-c','credential.helper=','ls-remote','--',repository,'HEAD']
    recorded = [re.sub(r'^((?:git\+)?https?://)[^/]*@', r'\1', value, flags=re.I) for value in argv]
    env = dict(options.get('env') or {}, LC_ALL='C', GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='', SSH_ASKPASS='', SSH_ASKPASS_REQUIRE='never')
    with open(os.open(log_path, os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_APPEND, 0o600), 'a+b') as log:
        result = await _execute_package_query(directory, argv, dict(options,env=env,_stderrFile=log))
        if result['exitCode'] == 0 and not result.get('cause') and not result['timedOut']:return None
        if result['timedOut']:log.write(('dsh: connection to '+spec['host']+' timed out after '+str(options['timeoutMs'])+'ms\n').encode('utf-8'))
        if os.fstat(log.fileno()).st_size == 0:
            cause = result.get('cause')
            log.write((getattr(cause,'message',None) or 'Git connection check failed').encode('utf-8'))
        log.flush();size=os.fstat(log.fileno()).st_size
        log.seek(max(0,size-options['outputBytes']));output=log.read().decode('utf-8',errors='replace')
    answer = dict(argv=recorded, exitCode=result['exitCode'] if result['exitCode'] is not None else (127 if getattr(result.get('cause'),'code',None)=='ENOENT' else 1),
        output=output,truncated=size>options['outputBytes'],logPath=log_path,kind=classify_install_failure(dict(log=output,timedOut=result['timedOut'])))
    if result['timedOut']:answer['timedOut']=True
    return answer
