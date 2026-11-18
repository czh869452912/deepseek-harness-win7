"""Observe layered route-name validation without touching the launch environment."""
import asyncio
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
NAMES = ['HTTP_PROXY', 'http_proxy', 'Https_Proxy', 'ALL_PROXY', 'NO_PROXY',
         'DEEPSEEK_BASE_URL', 'DEEPSEEK_SEARCH_BASE_URL', 'deepseek_base_url',
         'DeepSeek_Search_Base_URL', 'SSL_CERT_FILE', 'NODE_TLS_REJECT_UNAUTHORIZED', 'DSH_HOME']


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text(json.dumps(NAMES), encoding='utf-8')
    return [path]


async def native():
    from dsh.boot.app_boot import load_layered_env
    inherited = dict(os.environ)
    result = []
    try:
        for index, name in enumerate(NAMES):
            for mode in ('home', 'project', 'same', 'inherited'):
                directory = OUTPUT/'files'/'native'/str(index)/mode
                home, project = directory/'home', directory/'project'
                home.mkdir(parents=True); project.mkdir()
                if mode == 'same':
                    project = home
                target = project if mode == 'project' else home
                (target/'.env').write_text(name+'=route\n', encoding='utf-8')
                if mode != 'same':
                    other = home if mode == 'project' else project
                    (other/'.env').write_text('ORDINARY=checked\n', encoding='utf-8')
                os.environ.clear(); os.environ['DSH_HOME'] = str(home)
                if mode == 'inherited' and name != 'DSH_HOME':
                    os.environ[name] = 'inherited'
                failure = None; snapshot = None
                try:
                    snapshot = load_layered_env('probe', str(project), home=str(home))
                except ValueError as error:
                    failure = str(error).replace(str(directory), '$ROOT')
                result.append(dict(name=name, mode=mode, error=failure,
                    value=os.environ.get(name), ordinary=os.environ.get('ORDINARY'),
                    entry=None if snapshot is None else snapshot.get(name)))
                row = result[-1]
                # DSH_HOME is the owned test location, not test output identity.
                if name == 'DSH_HOME':
                    row['value'] = row['value'].replace(str(directory), '$ROOT')
                if row['entry'] is not None and 'path' in row['entry']:
                    row['entry']['path'] = row['entry']['path'].replace(str(directory), '$ROOT')
        return result
    finally:
        os.environ.clear(); os.environ.update(inherited)


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_environment.mts', 'Home route names, exact endpoint spelling, project refusal, inherited precedence and atomic validation.',
        [ROOT/'dsh/boot/app_boot.py', ROOT/'dsh/cordis/environment.py', Path(__file__).resolve(),
         ROOT/'reference/packages/boot/app-boot/src/index.ts'], prepare)
