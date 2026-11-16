"""Git update orchestration with actual Git and loopback HTTP refusals."""
import asyncio
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe,rc022_manager_update_probe as update

CASES=['git-live','git-disabled','git-target-fails','git-restore-fails','git-activation-error','git-cancel','git-network','git-permission','git-no-command']
FIXTURE=None


class GitFixture:
    def __init__(self,root):
        root.mkdir(parents=True,exist_ok=False);self.root=root;self.requests=[];self.commands=[]
        config=root/'git.config';config.write_text('',encoding='utf-8')
        self.env=dict(GIT_CONFIG_GLOBAL=str(config),GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_COUNT='0')
        repository=root/'repository';repository.mkdir()
        def git(args):
            command=['git']+args;result=subprocess.run(command,cwd=str(repository),env=dict(os.environ,**self.env),capture_output=True,encoding='utf-8',errors='replace',timeout=10)
            self.commands.append(dict(argv=command,exitCode=result.returncode,stdout=result.stdout,stderr=result.stderr));result.check_returncode();return result.stdout.strip()
        git(['init','--initial-branch=main'])
        def commit(version):
            (repository/'README').write_text(version,encoding='utf-8');git(['add','.']);git(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','commit','-m',version]);return git(['rev-parse','HEAD'])
        previous=commit('1.0.0');target=commit('2.0.0')
        requests=self.requests
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status=403 if self.path.startswith('/forbidden/') else 503;requests.append(dict(path=self.path,status=status));self.send_response(status);self.send_header('Content-Length','0');self.end_headers()
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.plan={}
        for case in CASES:
            base=('git+http://127.0.0.1:'+str(self.server.server_port)+('/forbidden/repository.git' if case=='git-permission' else '/offline/repository.git') if case in ('git-network','git-permission') else 'git+'+repository.as_uri())
            env=dict(self.env)
            if case=='git-no-command':env['PATH']=''
            self.plan[case]=dict(previous=base+'#'+previous,target=base+'#'+target,env=env)

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        (self.root.parent/'git-observations.json').write_text(json.dumps(dict(commands=self.commands,requests=self.requests),indent=2),encoding='utf-8')


async def observe(workspace=None):
    global FIXTURE
    fixture=FIXTURE if workspace is None else GitFixture(workspace/'git-fixture')
    before_cases=update.corpus;before_git=update.GIT
    try:
        update.corpus=lambda:CASES;update.GIT=fixture.plan
        return await update.observe(workspace)
    finally:
        update.corpus=before_cases;update.GIT=before_git
        if workspace is not None:fixture.close()


def prepare(output):
    global FIXTURE
    update.WORKSPACE=output/'files';update.WORKSPACE.mkdir();FIXTURE=GitFixture(update.WORKSPACE/'git-fixture')
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(update.WORKSPACE),python=str(Path(sys.executable).resolve()),program=update.PROGRAM,cases=CASES,git=FIXTURE.plan)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_manager_update.mts','Actual manager Git update with two real repository commits, real git ls-remote, loopback HTTP503/403, and explicitly missing Git. Package mutations controlled; real package acquisition is not claimed.',[Path(__file__).resolve(),ROOT/'scripts/rc022_manager_update_probe.py',ROOT/'dsh/boot/plugin_update.py',ROOT/'dsh/boot/plugin_git_connection.py'],prepare=prepare)
    finally:
        if FIXTURE is not None:FIXTURE.close()
