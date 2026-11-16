"""Managed reference precedence and safe previews over real credential files."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

WORKSPACE = None


def cases():
    values = [None, 'short', 'x'*16, 'x'*17, 'sk-'+'x'*16, 'sk-'+'x'*17, 'provider_'+'a'*17,
              'a-b_c'+'x'*18, '\U0001f600'*16, '\U0001f600'*17, 'id-'+('e\u0301'*10), 'first\nsecond\nthird line']
    return [dict(process=process, project=project, user=user, stored=value)
            for process, project, user in [(None, None, None), ('', 'project', 'user'), (None, 'project', 'user'),
                                           ('process', 'project', 'user'), (None, None, 'user')]
            for value in values]


def prepare(output):
    global WORKSPACE
    WORKSPACE = output/'files/native'
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


async def observe(workspace=None):
    import asyncio
    import yaml
    from dsh.cordis.context import Context
    from dsh.cordis.environment import LaunchEnvironmentSnapshot
    from dsh.credentials.credentials_local import CredentialsLocalPlugin
    directory = workspace if workspace is not None else WORKSPACE
    assert directory is not None
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, entry in enumerate(cases()):
        filename = directory/(str(index)+'.yaml')
        initial = dict(version=1, refs={} if entry['stored'] is None else dict(TEST_KEY=entry['stored']))
        filename.write_text(yaml.safe_dump(initial, allow_unicode=True), encoding='utf-8')
        ctx = Context(); events = []
        layers = [dict(source=source, values={} if entry[key] is None else dict(TEST_KEY=entry[key]))
                  for source, key in [('process', 'process'), ('project-env', 'project'), ('user-env', 'user')]]
        ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot(layers))
        ctx.on('credentials/reference-updated', lambda ref: events.append(ref))
        try:
            await ctx.plugin(CredentialsLocalPlugin, dict(path=str(filename), watch=False))
            service = ctx.credentials
            async def snapshot():
                for _ in range(2): await asyncio.sleep(0)
                return dict(value=service.resolve('TEST_KEY'), info=service.describe('TEST_KEY'), events=list(events))
            result = [await snapshot()]
            service.set('TEST_KEY', 'new-provider_'+'z'*20); result.append(await snapshot())
            service.unset('TEST_KEY'); result.append(await snapshot())
            service.unset('TEST_KEY'); result.append(await snapshot())
            try: service.set('TEST_KEY', '')
            except Exception as error: result.append(dict(error=str(error)))
            disk = yaml.safe_load(filename.read_text(encoding='utf-8'))
            rows.append(dict(result=result, refs=disk['refs'], layers=layers))
        finally: await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_local_credentials.mts', 'Actual file-backed credential reference precedence, masked code-point previews, set/unset and frozen environment layers.',
               [Path(__file__).resolve(), ROOT/'dsh/credentials/credentials_local.py', ROOT/'dsh/credentials/types.py'], prepare=prepare)
