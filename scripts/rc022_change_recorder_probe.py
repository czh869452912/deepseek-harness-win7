"""Exercise actual original/native turn recorders against identical file edits."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_change_git_probe import git, repo_state

OUTPUT = None


def cases():
    return [
        dict(name='edit-once', initial={'a.txt': 'old\n'}, ops=[['capture', 'a.txt'], ['write', 'a.txt', 'new\n'], ['capture', 'a.txt'], ['write', 'a.txt', 'latest\n'], ['result', 10, 1], ['stop', 1], ['collect'], ['end', 1], ['collect']]),
        dict(name='no-tool-result', ops=[['capture', 'a.txt'], ['write', 'a.txt', 'new\n'], ['stop', 1], ['collect']]),
        dict(name='wrong-turn', ops=[['capture', 'a.txt'], ['write', 'a.txt', 'new\n'], ['result', 10, 2], ['stop', 2], ['end', 2], ['collect']]),
        dict(name='empty-supersedes', initial={'a.txt': 'old\n'}, ops=[['capture', 'a.txt'], ['write', 'a.txt', 'new\n'], ['result', 10, 1], ['stop', 1], ['collect'], ['write', 'a.txt', 'old\n'], ['result', 11, 1], ['end', 1], ['collect']]),
        dict(name='created-and-deleted', initial={'gone.txt': 'gone\n'}, ops=[['capture', 'new.txt'], ['write', 'new.txt', 'created\n'], ['capture', 'gone.txt'], ['delete', 'gone.txt'], ['result', 10, 1], ['end', 1], ['collect']]),
        dict(name='binary-and-cap', maxFileBytes=8, initial={'binary': 'old\n', 'large': '012345678'}, ops=[['capture', 'binary'], ['write', 'binary', 'x\u0000y'], ['capture', 'large'], ['write', 'large', 'tiny'], ['result', 10, 1], ['stop', 1], ['collect']]),
        dict(name='list-cap-counts', maxFiles=1, ops=[['capture', 'z'], ['write', 'z', 'z\nz\n'], ['capture', 'a'], ['write', 'a', 'a\n'], ['result', 10, 1], ['stop', 1], ['collect']]),
        dict(name='next-turn-isolated', initial={'a': 'one\n'}, ops=[['capture', 'a'], ['write', 'a', 'two\n'], ['result', 10, 1], ['stop', 1], ['collect'], ['start', 2], ['capture', 'a'], ['write', 'a', 'three\n'], ['result', 11, 2], ['end', 2], ['collect']]),
        dict(name='outside-temporary-excluded', ops=[['capture', '../temp/outside'], ['write', '../temp/outside', 'temporary\n'], ['result', 10, 1], ['stop', 1], ['collect']]),
        dict(name='git-snapshot-and-ignored', git=True, initial={'.gitignore': 'ignored\n', 'tracked': 'base\n', 'ignored': 'before\n'}, ops=[['write', 'tracked', 'updated\n'], ['capture', 'ignored'], ['write', 'ignored', 'changed\n'], ['write', 'uncaptured', 'new\n'], ['result', 10, 1], ['stop', 1], ['collect']]),
        dict(name='git-lazy-cap', git=True, maxFileBytes=8, initial={'large': '012345678\n'}, ops=[['write', 'large', 'changed\n'], ['result', 10, 1], ['end', 1], ['collect']]),
        dict(name='git-renamed', git=True, initial={'before': 'same\n'}, ops=[['delete', 'before'], ['write', 'after', 'same\n'], ['result', 10, 1], ['stop', 1], ['collect']]),
    ]


def prepare(output):
    global OUTPUT
    OUTPUT = output
    for side in ('source', 'native'):
        for index, case in enumerate(cases()):
            base = output/'files'/side/str(index)
            cwd = base/'cwd'
            cwd.mkdir(parents=True)
            (base/'temp').mkdir()
            for name, text in case.get('initial', {}).items():
                (cwd/name).write_bytes(text.encode('utf-8'))
            if case.get('git'):
                git(cwd, 'init', '-q')
                git(cwd, 'config', 'user.name', 'Fixture')
                git(cwd, 'config', 'user.email', 'fixture@example.invalid')
                git(cwd, 'config', 'core.autocrlf', 'false')
                git(cwd, 'add', '--all')
                git(cwd, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
    path = output/'input.json'
    path.write_text(json.dumps(dict(root=str(output/'files'), cases=cases())), encoding='utf-8')
    return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
    from dsh.core.abort import NEVER_ABORTED
    from dsh.deliverables.change_git import GitRunner
    from dsh.deliverables.change_recorder import TurnRecorder
    ctx = Context()
    await ctx.plugin(AuthorizedLocalSubprocessRuntime)
    rows = []
    original_temp = tempfile.tempdir
    try:
        for index, case in enumerate(cases()):
            base = OUTPUT/'files'/'native'/str(index)
            cwd = base/'cwd'
            tempfile.tempdir = str(base/'temp')
            events, warnings, snapshots = [], [], []
            class Session:
                def append(self, type, data):
                    event = dict(seq=len(events), type=type, data=data)
                    events.append(event)
                    return event
            before = repo_state(cwd) if case.get('git') else None
            runner = GitRunner(ctx.subprocess, 'git', dict(timeoutMs=30000, outputMaxBytes=1048576)) if case.get('git') else None
            recorder = TurnRecorder(Session(), str(cwd), dict(git=runner, tempRoot=str(base/'temp'),
                maxFiles=case.get('maxFiles', 500), maxFileBytes=case.get('maxFileBytes', 1048576), diffTimeoutMs=1000, warn=warnings.append))
            try:
                recorder.start(1)
                await recorder.settled()
                for op in case['ops']:
                    if op[0] == 'start': recorder.start(op[1])
                    elif op[0] == 'capture': recorder.capture(os.path.abspath(str(cwd/op[1])))
                    elif op[0] == 'write': (cwd/op[1]).write_bytes(op[2].encode('utf-8'))
                    elif op[0] == 'delete': (cwd/op[1]).unlink()
                    elif op[0] == 'result': recorder.observe(dict(seq=op[1], data=dict(turn=op[2])))
                    elif op[0] == 'stop': await recorder.stopping(op[1])
                    elif op[0] == 'end': recorder.end(op[1])
                    elif op[0] == 'collect':
                        await recorder.settled()
                        records = []
                        for event in events:
                            summary = recorder.summary(event['seq'])
                            records.append(dict(summary=dict(summary, cwd='<cwd>'),
                                diffs=[await recorder.diff(event['seq'], index, NEVER_ABORTED) for index in range(len(summary['files'])+1)]))
                        snapshots.append(records)
                    await recorder.settled()
                unknown = await recorder.diff(999, 0, NEVER_ABORTED)
            finally:
                await recorder.dispose()
            rows.append(dict(name=case['name'], snapshots=snapshots, events=events, warnings=warnings,
                unknown=unknown, disposed=recorder.summary(0), scratchRemoved=not list((base/'temp').glob('dsh-workspace-changes-*')),
                untouched=before is None or before == repo_state(cwd)))
    finally:
        tempfile.tempdir = original_temp
        await ctx.fiber.dispose()
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_change_recorder.mts',
        'Actual per-turn recorder: first mutation, no results/wrong turns, empty supersession, create/delete, '
        'binary/size/list caps, consecutive turns, temporary exclusions, real Git/ignored files/rename/lazy blobs, disposal and private repository state.',
        [Path(__file__).resolve(), ROOT/'dsh/deliverables/change_recorder.py'], prepare=prepare)
