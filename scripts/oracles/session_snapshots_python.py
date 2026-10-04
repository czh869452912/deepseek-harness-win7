import argparse
import asyncio
import json
import importlib.util
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
arguments = None
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--root',type=Path,default=ROOT)
    arguments = parser.parse_args()
    ROOT = arguments.root.resolve()
sys.path.insert(0,str(ROOT))
import dsh
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader
from dsh.core.session.session import SessionPlugin
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin
from dsh.session.persistence_sqlite import SqliteSessionPersistencePlugin

fixture_spec = importlib.util.spec_from_file_location('session_snapshot_fixture', Path(__file__).with_name('session_snapshot_fixture.py'))
fixture = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture)


async def observe():
    rows = []
    for backend in ('jsonl','sqlite'):
        modes = ['lazy','stable','append','noop','detached','reopen','copy','preabort',
                 'restored-stat' if backend == 'jsonl' else 'memory']
        for mode in modes:
            parent = Path(tempfile.mkdtemp(prefix='dsh-snapshot-'))
            root = parent/'original'
            file = parent/'original.db'
            header = SessionHeader(session_id='s',created_at=1)
            first_event = dict(type='session/end-seed',seq=0,time=1,data={})
            context = None
            async def mount(location):
                nonlocal context
                context = Context()
                await context.plugin(SessionPlugin)
                await context.plugin(JsonlSessionPersistencePlugin if backend == 'jsonl' else SqliteSessionPersistencePlugin,
                    dict(root=str(location)) if backend == 'jsonl' else dict(path=str(location)))
                return context.get('sessionPersistence')
            def grammar(token):
                return re.fullmatch(r'\d+:\d+:\d+:-?\d+:-?\d+',token) is not None if backend == 'jsonl' else re.fullmatch(
                    r'(?:file:\d+:\d+:-?\d+|memory):store:[0-9a-f-]{36}:incarnation:[0-9a-f-]{36}:revision:\d+',token) is not None
            observed = {}
            reason = TypeError('snapshot deadline')
            try:
                persistence = await mount(':memory:' if mode == 'memory' else root if backend == 'jsonl' else file)
                await persistence.create(header)
                if mode == 'lazy':
                    observed['count'] = len(await persistence.listSnapshots())
                elif mode == 'preabort':
                    controller = AbortController()
                    controller.abort(reason)
                    await persistence.listSnapshots(controller.signal)
                else:
                    await persistence.append(header.id,[first_event])
                    initial = (await persistence.listSnapshots())[0]
                    if mode == 'stable':
                        repeated = await persistence.listSnapshots()
                        identity = os.stat(persistence.locate(header).path if backend == 'jsonl' else str(file))
                        prefix = ':'.join(str(value) for value in (
                            identity.st_dev,identity.st_ino,identity.st_size,identity.st_mtime_ns))+':' if backend == 'jsonl' else (
                            'file:{}:{}:{}:store:'.format(identity.st_dev,identity.st_ino,identity.st_ctime_ns))
                        observed.update(count=len(repeated),same=repeated[0].revision==initial.revision,
                                        qualified=grammar(initial.revision),statIdentity=initial.revision.startswith(prefix))
                    elif mode in ('append','memory'):
                        await persistence.append(header.id,[
                            dict(type='turn/start',seq=1,time=2,data=dict(turn=1)),
                            dict(type='turn/end',seq=2,time=3,data=dict(turn=1,reason=dict(kind='completed'))),
                        ])
                        next_snapshot = (await persistence.listSnapshots())[0]
                        if mode == 'memory':
                            observed.update(qualified=grammar(initial.revision),
                                same=(await persistence.listSnapshots())[0].revision==next_snapshot.revision,
                                counterDelta=int(next_snapshot.revision.split(':')[-1])-int(initial.revision.split(':')[-1]))
                        else:
                            observed['changed'] = initial.revision != next_snapshot.revision
                            if backend == 'sqlite':
                                observed['counterDelta'] = int(next_snapshot.revision.split(':')[-1])-int(initial.revision.split(':')[-1])
                    elif mode == 'noop':
                        await persistence.append(header.id,[])
                        observed['same'] = (await persistence.listSnapshots())[0].revision==initial.revision
                    elif mode == 'detached':
                        initial.header.created_at = 999
                        repeated = (await persistence.listSnapshots())[0]
                        observed.update(createdAt=repeated.header.created_at,sameToken=repeated.revision==initial.revision)
                    elif mode in ('reopen','copy'):
                        await context.fiber.dispose()
                        context = None
                        location = root if backend == 'jsonl' else file
                        if mode == 'copy':
                            location = parent/('copied' if backend == 'jsonl' else 'copied.db')
                            if backend == 'jsonl':
                                shutil.copytree(str(root),str(location))
                            else:
                                shutil.copyfile(str(file),str(location))
                        persistence = await mount(location)
                        repeated = (await persistence.listSnapshots())[0]
                        if mode == 'reopen':
                            observed.update(same=repeated.revision==initial.revision,qualified=grammar(repeated.revision))
                        else:
                            observed.update(sameHeader=repeated.header.to_dict()==initial.header.to_dict(),
                                            different=repeated.revision!=initial.revision,qualified=grammar(repeated.revision))
                    else:
                        path = persistence.locate(header).path
                        os.utime(path,ns=(1000000000000000000,1000000000000000000))
                        fixture.set_change_time(path, 1500000000000000000)
                        before = os.stat(path)
                        first = (await persistence.listSnapshots())[0]
                        bytes_value = bytearray(Path(path).read_bytes())
                        bytes_value[-2] = 32
                        Path(path).write_bytes(bytes_value)
                        os.utime(path,ns=(1000000000000000000,1000000000000000000))
                        fixture.set_change_time(path, 1500000001000000000)
                        after = os.stat(path)
                        next_snapshot = (await persistence.listSnapshots())[0]
                        observed.update(sameSize=before.st_size==after.st_size,sameFile=before.st_ino==after.st_ino,
                            sameMtime=before.st_mtime_ns==after.st_mtime_ns,changedToken=first.revision!=next_snapshot.revision,
                            changeFieldAdvanced=int(next_snapshot.revision.split(':')[-1])>int(first.revision.split(':')[-1]))
            except Exception as error:
                observed['error'] = dict(name=type(error).__name__,message=getattr(error,'message',str(error)),sameReason=error is reason)
            finally:
                if context is not None:
                    await context.fiber.dispose()
                shutil.rmtree(str(parent))
            rows.append(dict(name=backend+'-'+mode,observed=observed))
    return rows


def main():
    observations = asyncio.run(observe())
    arguments.output.write_text(json.dumps(dict(observations=observations,root=str(ROOT),
        module=str(Path(dsh.__file__).resolve()),python=list(sys.version_info[:3])),ensure_ascii=True,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
