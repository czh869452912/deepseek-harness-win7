"""Paired Git preflight reads using real Git, loopback HTTP and local repositories."""
import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None;FIXTURE=None;SERVER=None


def corpus():
    return ['pkg','github:org/repo','https://git.example/team/repo.git#main&path:/a b',
        'git+https://git.example:8443/team/repo.git#main','http://git.example/repo.git#x',
        'https://user:secret@git.example/repo.git','https://git.example/repo.git?q=x',
        'https://git.example/repo.git?','https://git.example/a/../repo.git#hello world',
        'https://git.example/a/%2e%2e/repo.git','https://[::1]:8443/repo.git#x',
        'https://GIT.EXAMPLE/a.git','https://git.example/a%20b.git#x',
        'https://git.example/a[repo]^name|.git#x','https://git.example/a\\repo.git',
        'https://github.com/extra/../org/repo.git','https://gitlab.com/org/%ZZ/repo.git',
        'git+ssh://git@git.example/repo.git','git@git.example:repo.git']+[
        prefix+host+path for prefix in ('https://','http://','git+https://')
        for host in ('github.com','www.github.com','gitlab.com','bitbucket.org','gist.github.com','git.sr.ht')
        for path in ('/org/repo.git','/org/repo.git/extra','/org/.git')]


def modes():return ['http-success','ssh-success','both-fail','transport-cancel','check-success','check-http','check-auth','check-credentials','check-tail','check-timeout','check-cancel','github-skip','github-subdomain']


def fixture(root):
    root.mkdir(parents=True,exist_ok=True);repo=root/'repository.git';work=root/'work'
    def git(*args):subprocess.run(['git',*map(str,args)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    git('init','--bare',repo);git('init',work)
    git('-C',work,'-c','user.name=t','-c','user.email=t@t','-c','commit.gpgsign=false','commit','--allow-empty','-m','init')
    git('-C',work,'push',repo,'HEAD:refs/heads/main');git('-C',repo,'symbolic-ref','HEAD','refs/heads/main')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path.startswith('/slow'):self.server.stop_event.wait(10)
            status=401 if self.path.startswith('/auth') else 500
            try:
                self.send_response(status)
                if status==401:self.send_header('WWW-Authenticate','Basic realm="fixture"')
                self.end_headers();self.wfile.write(b'failure')
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;server.stop_event=threading.Event()
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    return dict(repository=repo.resolve().as_uri(),url='http://127.0.0.1:'+str(server.server_port)),server


def stop(server):server.stop_event.set();server.shutdown();server.server_close()


def config_for(mode, info):
    if mode in ('http-success','check-success'):return '[url "'+info['repository']+'"]\n insteadOf = https://git.example/team/repo.git\n'
    endpoint='slow' if mode in ('transport-cancel','check-timeout','check-cancel') else 'auth' if mode in ('check-auth','check-credentials') else 'failure'
    config='[url "'+info['url']+'/'+endpoint+'/"]\n insteadOf = https://git.example/\n insteadOf = https://user:secret@git.example/\n insteadOf = https://sub.github.com/\n[http]\n proxy =\n'
    if mode=='ssh-success':config+='[url "'+info['repository']+'"]\n insteadOf = ssh://git@git.example/team/repo.git\n'
    else:config+='[url "file:///definitely-no-dsh-repository"]\n insteadOf = ssh://git@git.example/team/repo.git\n'
    return config


def normalize(result, directory, url):
    if result is None:return None
    result=dict(result);log=Path(result.pop('logPath'));data=log.read_bytes();output=result.pop('output')
    result.update(logBytes=len(data),logEndsWithOutput=data.endswith(output.encode('utf-8')),hasDiagnostic=bool(output))
    if result.get('timedOut'):result['timeoutDiagnostic']='timed out after 300ms' in output
    # Cancellation and silent-timeout diagnostics/exit status belong to Git,
    # curl and the host process launcher. Preserve semantic outcomes only here.
    if result.get('timedOut') or result.get('kind')=='unknown':
        result.pop('logBytes');result.pop('logEndsWithOutput');result['exitCode']=result['exitCode']!=0
    result['argv']=[arg.replace(url,'<loopback>') for arg in result['argv']]
    return result


async def observe(workspace=None):
    from dsh.boot.plugin_install_spec import parse_install_spec
    from dsh.boot.plugin_git_connection import ssh_git_spec,choose_git_transport,check_git_connection,check_github_connection
    from dsh.core.abort import AbortController
    rows=[]
    for spec in corpus():
        try:value=dict(value=ssh_git_spec(parse_install_spec(spec)))
        except Exception:value=dict(error=True)
        rows.append(dict(kind='ssh',spec=spec,result=value))
    own=workspace is not None
    info,server=fixture(workspace/'shared') if own else (FIXTURE,None)
    try:
        for mode in modes():
            directory=(workspace or WORKSPACE)/'native'/mode;directory.mkdir(parents=True)
            config=directory/'git.config';config.write_text(config_for(mode,info),encoding='utf-8')
            trace=directory/'trace.jsonl'
            env=dict(GIT_CONFIG_GLOBAL=str(config),GIT_CONFIG_NOSYSTEM='1',GIT_TRACE2_EVENT=str(trace))
            control=AbortController();options=dict(timeoutMs=300 if mode=='check-timeout' else 3000,outputBytes=4 if mode=='check-tail' else 4096,signal=control.signal,env=env)
            timer=asyncio.get_running_loop().call_later(.3,control.abort) if mode in ('transport-cancel','check-cancel') else None
            text='https://user:secret@git.example/team/repo.git#main' if mode=='check-credentials' else 'https://sub.github.com/team/repo.git' if mode=='github-subdomain' else 'https://git.example/team/repo.git#main'
            parsed=parse_install_spec(text)
            try:
                if mode in ('http-success','ssh-success','both-fail','transport-cancel'):result=await choose_git_transport(parsed,str(directory),options)
                else:
                    operation=check_github_connection if mode in ('github-skip','github-subdomain') else check_git_connection
                    result=normalize(await operation(parsed,str(directory),options),directory,info['url'])
            finally:
                if timer:timer.cancel()
            commands=[json.loads(line)['argv'][1:] for line in trace.read_text(encoding='utf-8').splitlines() if json.loads(line).get('event')=='start' and 'ls-remote' in json.loads(line).get('argv',[])] if trace.exists() else []
            rows.append(dict(kind='actual',mode=mode,result=result,commands=commands))
        return rows
    finally:
        if server:stop(server)


def prepare(output):
    global WORKSPACE,FIXTURE,SERVER
    WORKSPACE=output/'files';WORKSPACE.mkdir();FIXTURE,SERVER=fixture(WORKSPACE/'shared')
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),fixture=FIXTURE,specs=corpus(),modes=modes())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_git_connection.mts','Actual Git transport and connection probes using shared bare repository, Git URL rewrites, isolated config and loopback HTTP. Pure SSH serialization includes known hosted-Git exclusions. OS cancellation diagnostics and exit codes normalized to semantic failure presence.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_git_connection.py',ROOT/'dsh/boot/plugin_package_view.py'],prepare=prepare)
    finally:
        if SERVER:stop(SERVER)
