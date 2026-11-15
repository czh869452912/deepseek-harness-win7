"""Paired whole-patch admission and truthful sequential effects on real files."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def corpus():
    def patch(*operations):return '\n'.join(['*** Begin Patch']+list(operations)+['*** End Patch'])
    def add(path,content='new'):return '*** Add File: '+path+'\n+'+content
    def update(path,old='old',new='new',destination=None):return '*** Update File: '+path+('' if destination is None else '\n*** Move to: '+destination)+'\n@@\n-'+old+'\n+'+new
    def delete(path):return '*** Delete File: '+path
    initial=dict(edit='old\r\n',source='old\n',gone='gone\n')
    cases=[dict(name='syntax',patch='invalid'),dict(name='empty',patch=patch()),
        dict(name='all-four',files=initial,patch=patch(update('edit'),add('created'),delete('gone'),update('source',destination='destination'))),
        dict(name='repeated-alias',patch=patch(add('a','one'),update('./a','one','two'),update('a','two','three'),delete('./a'),add('a','four'))),
        dict(name='move-chain',files={'a':'old\n'},patch=patch(update('a',destination='b'),update('b','new','last',destination='c'))),
        dict(name='independent-refusals',files={'a':'old\n'},unread=['a'],absent=['b'],patch=patch(update('a'),update('b'),add('c'))),
        dict(name='blind-overwrite',files={'a':'keep'},unread=['a'],patch=patch(add('a'),add('b'))),
        dict(name='stale',files={'a':'old\n'},stale=['a'],patch=patch(update('a'),add('b'))),
        dict(name='missing-source',policy=False,patch=patch(delete('a'),update('b'),add('c'))),
        dict(name='directory',directories=['a'],patch=patch(add('a'),add('b'))),
        dict(name='mismatch',files={'a':'old\n'},patch=patch(add('first'),update('a','missing','new'),add('last'))),
        dict(name='unicode-preview',files={'a':'old\n'},patch=patch(update('a','🧪'*81,'new'))),
        dict(name='late-binary',files={'a':'old\n'+'x'*9000+'\0'},patch=patch(update('a'))),
        dict(name='same-target',files={'a':'old\n'},patch=patch(update('a',destination='./a'))),
        dict(name='move-overwrite',files={'a':'old\n','b':'prior\n'},patch=patch(update('a',destination='b'))),
        dict(name='unread-move-destination',files={'a':'old\n','b':'prior\n'},unread=['b'],patch=patch(update('a',destination='b'))),
        dict(name='bare-provider',policy=False,files={'a':'old\n'},unread=['a'],patch=patch(update('a')))]
    for hook in ['remove-denied','move-remove-denied','cancel-between','cancel-last','cancel-staged','io-unchanged','io-published','unexpected','aborted-mutation','post-write-stat-failure']:
        operation=update('source',destination='destination') if hook=='move-remove-denied' else delete('source') if hook=='remove-denied' else update('source') if hook in ['io-unchanged','io-published','unexpected','aborted-mutation','post-write-stat-failure'] else add('middle')
        cases.append(dict(name=hook,hook=hook,files={'source':'old\n'},patch=patch(add('first'),operation,add('last')) if hook!='cancel-last' else patch(add('first'))))
    return cases


async def observe():
    from dsh.cordis import Context
    from dsh.fs.local_current import CurrentFsLocal
    from dsh.fs.fs_observation_policy import CurrentFsObservationPolicy
    from dsh.fs.fs_local import FsError
    from dsh.fs.patch_executor import execute_patch
    from dsh.fs.tool_fs_sandbox import FsSandboxController
    from dsh.core.abort import AbortController
    rows=[]
    class Session:pass
    for case in corpus():
        base=WORKSPACE/'native'/case['name'];workspace=base/'workspace';workspace.mkdir(parents=True);provider=base/'provider';provider.mkdir()
        ctx=Context();await ctx.plugin(CurrentFsLocal,dict(cwd=str(provider)))
        ctx.set_service('workingDirectory',NS(ensure=lambda *_:None))
        async def ensure(*_):return str(workspace)
        ctx.workingDirectory.ensure=ensure
        if case.get('policy',True):await ctx.plugin(CurrentFsObservationPolicy)
        abort=AbortController();execution=NS(signal=abort.signal,agent=NS(session=Session()));fs=ctx.fs;observations=[]
        async def target(path):return await fs.resolve(str(workspace/path))
        for path in case.get('directories',[]):(workspace/path).mkdir(parents=True)
        for path,content in case.get('files',{}).items():
            (workspace/path).write_bytes(content.encode('utf-8'))
            if path not in case.get('unread',[]):
                item=await target(path);ctx.emit('fs/observed',item,dict(kind='present',version=(await fs.stat(item)).version),execution)
        for path in case.get('absent',[]):ctx.emit('fs/observed',await target(path),dict(kind='absent'),execution)
        for path in case.get('stale',[]):(workspace/path).write_bytes(b'changed\n')
        def observed(item,value,*_):
            observations.append(dict(path=item.displayPath,kind=value['kind']))
            if case.get('hook') in ('cancel-between','cancel-last'):abort.abort()
        ctx.on('fs/observed',observed)
        hook=case.get('hook')
        if hook in ('remove-denied','move-remove-denied'):
            def remove(_):
                error=RuntimeError('removal denied');error.code='EACCES';raise error
            fs.internals.removeFile=remove
        if hook=='cancel-staged':
            count=[0]
            def staged(_):
                count[0]+=1
                if count[0]==2:abort.abort()
            fs.internals.inspectTemp=staged
        if hook in ('io-unchanged','io-published','unexpected','aborted-mutation','post-write-stat-failure'):
            original=fs.patchText
            async def failing(*args,**kwargs):
                if hook in ('io-published','post-write-stat-failure'):await original(*args,**kwargs)
                if hook=='post-write-stat-failure':
                    async def bad_stat(*_):raise FsError('stat failed','FS_IO_ERROR')
                    fs.stat=bad_stat
                if hook=='unexpected':raise RuntimeError('defect')
                if hook=='aborted-mutation':abort.abort();raise FsError('patch aborted','FS_ABORTED')
                raise FsError('reply lost','FS_IO_ERROR')
            fs.patchText=failing
        try:
            try:report=await execute_patch(ctx,FsSandboxController(ctx),execution,dict(patch=case['patch']))
            except Exception as error:report=dict(thrown=dict(code=getattr(error,'code',None),message=str(error)))
            files={str(path.relative_to(workspace)).replace('\\','/'):path.read_bytes().decode('utf-8') for path in workspace.rglob('*') if path.is_file()}
            rows.append(dict(name=case['name'],report=report,observations=observations,files=files,providerEmpty=not any(provider.iterdir())))
        finally:await ctx.fiber.dispose()
    def normalize(value):
        if isinstance(value,str):return value.replace(str(WORKSPACE/'native'),'<root>')
        if isinstance(value,list):return [normalize(item) for item in value]
        if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
        return value
    return normalize(rows)


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'corpus.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),cases=corpus()),ensure_ascii=False),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_patch_execution.mts','Whole-patch syntax/admission, current-directory resolution, canonical aliases, observation and version guards, sequential ordered effects, partial move, cancellation boundaries, unchanged versus unknown provider failure, unexpected defect propagation; real file bytes and authoritative observations.',[Path(__file__).resolve(),ROOT/'dsh/fs/patch_executor.py',ROOT/'dsh/fs/fs_observation_policy.py'],prepare=prepare)
