"""Pending build permissions: actual YAML policy files, atomic refusals."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def corpus():
    report='[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: native@1.0.0, @scope/other@file:../other, @scope/*\n'
    fixtures=[None,'{}\n','# settings\nnodeLinker: hoisted\n','allowBuilds: {}\n',
        '# settings\nother: &unrelated value\ncopy: *unrelated\nallowBuilds:\n  native: set this to true or false # decision\n  denied: false\n  trusted: true\n  "@scope/*": set this to true or false\n',
        '{ other: yes, allowBuilds: { native: set this to true or false } }\n',
        'allowBuilds:\n  1: true\n  on: set this to true or false\n',
        'allowBuilds:\n  native: &pending set this to true or false\n  other: *pending\n',
        'allowBuilds: &builds\n  native: set this to true or false\nshared: *builds\n',
        'shared: &pending set this to true or false\nallowBuilds:\n  native: *pending\n',
        '[','[]\n','allowBuilds: false\n','allowBuilds: null\n',
        'allowBuilds: {native: false, native: true}\n','allowBuilds: {}\nallowBuilds: {}\n',
        'allowBuilds:\n  native: set this to true or false\n# trailing\n',
        'allowBuilds: {native: set this to true or false}\n# trailing\n']
    rows=[]
    for index,text in enumerate(fixtures):
        rows.append(dict(name='policy-'+str(index),text=text,output=report,approve=['native@1.0.0']))
    for name in ('native','missing','denied','*','--all'):
        rows.append(dict(name='approve-'+('wildcard' if name=='*' else name),text='allowBuilds:\n  native: set this to true or false\n  denied: false\n',output='',approve=['native',name]))
    for index,key in enumerate(['@scope/pkg@git+https://example.com/pkg#commit','@scope/pkg@git+https://user:token@example.com/pkg#commit',
            '@scope/pkg@git+http://token@example.com/pkg#commit','@scope/pkg@git+ssh://git:secret@example.com/pkg#commit',
            '@scope/pkg@git+ssh://git@example.com/pkg#commit','@scope/pkg@git+file:///repo#commit&path:plugin folder']):
        for eol in ('\n','\r\n'):
            rows.append(dict(name='git-'+str(index)+'-'+str(len(eol)),text=None,output=eol.join(['ERR_PNPM_GIT_DEP_PREPARE_NOT_ALLOWED','allowBuilds:','  '+key+': true','']),approve=[key]))
    for index,output in enumerate(['','Ignored build scripts: \n','Ignored build scripts: @scope/*, native@?\n',
            'Ignored build scripts: native, native, other\n','Ignored build scripts: native\u2028other','Ignored build scripts: \ufeffnative\u00a0',
            'Ignored build scripts: native\nIgnored build scripts: second\n']):
        rows.append(dict(name='report-'+str(index),text='{}\n',output=output,approve=[]))
    return rows


async def observe(workspace=None):
    from dsh.boot.plugin_build_approval import record_pending_builds,approve_builds,blocked_build_names
    rows=[]
    for item in corpus():
        directory=(workspace or WORKSPACE)/'native'/item['name'];directory.mkdir(parents=True)
        path=directory/'pnpm-workspace.yaml'
        if item['text'] is not None:
            with path.open('w',encoding='utf-8',newline='') as stream:stream.write(item['text'])
        def content():return path.read_bytes() if path.exists() else None
        initial=content()
        async def result(operation):
            try:return dict(value=await operation())
            except Exception as error:return dict(error='stale-approval' if getattr(error,'code',None)=='stale-approval' else 'error')
        recorded=await result(lambda:record_pending_builds(str(directory),item['output']))
        before=content()
        approved=await result(lambda:approve_builds(str(directory),item['approve']))
        # JS undefined is omitted from JSON; an approval success carries no value.
        if approved==dict(value=None):approved={}
        after=content()
        pending=await result(lambda:record_pending_builds(str(directory),''))
        rows.append(dict(name=item['name'],blocked=blocked_build_names(item['output']),recorded=recorded,approved=approved,pending=pending,
            recordedChanged=before!=initial,approvedChanged=before!=after,exists=path.exists(),
            comments=after is not None and b'# settings' in after,unrelated=after is not None and b'&unrelated value' in after))
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_build_approval.mts','Pending build scripts recorded from non-interactive reports with credential-bearing Git keys excluded. Real YAML block/flow policies preserve unrelated anchors/comments; shared approval nodes, malformed/duplicate records and stale approvals reject before changing bytes. Exact scopes/file/subdirectory selectors, CRLF, report order and idempotence; no script execution.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_build_approval.py'],prepare=prepare)
