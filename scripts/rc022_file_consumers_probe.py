"""Current file tool consumers over an explicit remote-shaped filesystem collaborator."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    cases=[]
    def add(name,tool,arguments,**options):cases.append(dict(name=name,tool=tool,arguments=arguments,**options))
    for mode in ('whole','stream','unknown','missing','directory'):
        add('read-'+mode,'read',dict(file_path='file.ts'),mode=mode)
    add('read-window','read',dict(file_path='file.ts',offset=2,limit=1))
    add('read-unicode','read',dict(file_path='file.ts'),text='测试🧪tail\nnext\nlast\n',maxBytes=12)
    for mode in ('create','update','identical'):
        add('write-'+mode,'write',dict(file_path='file.ts',content='new\n'),mode=mode)
    add('edit','edit',dict(file_path='file.ts',old_string='old',new_string='new'))
    add('edit-all','edit',dict(file_path='file.ts',old_string='old',new_string='new',replace_all=True))
    for tool in ('write','edit'):
        arguments=dict(file_path='file.ts',content='new') if tool=='write' else dict(file_path='file.ts',old_string='old',new_string='new')
        for code in ('FS_NOT_OBSERVED','FS_STALE_VERSION','FS_PERMISSION_DENIED'):
            add(tool+'-'+code,tool,arguments,code=code)
    for tool in ('read','write','edit'):
        arguments=dict(file_path=' \ufeff ',content='new') if tool=='write' else dict(file_path=' \ufeff ',old_string='old',new_string='new') if tool=='edit' else dict(file_path=' \ufeff ')
        add(tool+'-blank',tool,arguments)
        add(tool+'-not-js-whitespace',tool,dict(arguments,file_path='\u0085'))
    add('read-offset','read',dict(file_path='file.ts',offset=0))
    add('read-fraction','read',dict(file_path='file.ts',limit=1.5))
    add('read-limit','read',dict(file_path='file.ts',limit=3))
    add('edit-empty','edit',dict(file_path='file.ts',old_string='',new_string='new'))
    add('edit-noop','edit',dict(file_path='file.ts',old_string='same',new_string='same'))
    return cases


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.fs.tools_current import CurrentPatchToolFs
    from dsh.fs.fs_local import FsError,FsTarget
    rows=[]
    for case in corpus():
        ctx=Context();definitions={};sections=[];effects=[];calls=[];hidden=set()
        class Tools:
            def register(self,definition):definitions[definition['name']]=definition
            def get(self,name,scope=None):return None if name in hidden else definitions.get(name)
        ctx.set_service('tools',Tools())
        ctx.set_service('systemPrompt',NS(section=lambda section:sections.append(section),getSectionOrder=lambda name:dict(TOOL_READ=1100,TOOL_WRITE=1200,TOOL_EDIT=1300)[name]))
        async def ensure(*_):calls.append('directory');return '/session/current'
        ctx.set_service('workingDirectory',NS(ensure=ensure))
        async def resolve(path,options):calls.append(dict(resolve=path,cwd=options.get('cwd'),signal=options.get('signal') is NEVER_ABORTED));return FsTarget(target_key=path,display_path='/display/'+path)
        def process_path(target):calls.append('processPath');return '/canonical/'+target.targetKey
        async def stat(*_):
            mode=case.get('mode');calls.append('stat')
            return None if mode=='missing' else NS(type='directory' if mode=='directory' else 'file',size=None if mode=='unknown' else 100 if mode=='stream' else 4,version='v1')
        async def read(*_):calls.append('read');return case.get('text','old\nsecond\nlast\n')
        async def stream(*_):
            calls.append('stream')
            async def chunks():
                for text in ['old\nse','cond\nlast\n']:yield text
            return chunks()
        async def mutation(target,*args,**kwargs):
            calls.append(dict(mutation=case['tool'],target=target.targetKey))
            if case.get('code'):raise FsError('provider reason',case['code'])
            return NS(version='v2',operation='create' if case.get('mode')=='create' else 'update',before=None if case.get('mode')=='create' else 'new\n' if case.get('mode')=='identical' else 'old\n',after='new\n')
        async def edit(*args,**kwargs):
            value=await mutation(*args,**kwargs);del value.operation;return value
        ctx.set_service('fs',NS(resolve=resolve,processPath=process_path,stat=stat,readText=read,streamText=stream,writeText=mutation,editText=edit))
        ctx.on('fs/observed',lambda target,value,*_:effects.append(dict(path=target.displayPath,**value)))
        try:
            await ctx.plugin(CurrentPatchToolFs,dict(readLimit=2,readMaxBytes=case.get('maxBytes',1024),readStreamMinSize=50))
            definition=definitions[case['tool']];arguments=case['arguments'];execution=NS(agent=NS(session=object()),signal=NEVER_ABORTED)
            try:
                value=await definition['execute'](arguments,execution);meta=definition['output']['presentationMeta'](arguments,value);content=definition['output']['render'](arguments,value)
                result=dict(value=value,meta=meta,content=content,presentation=definition['presentResult'](arguments,dict(isError=False,meta=meta,content=content)))
            except Exception as error:result=dict(error=dict(name=getattr(error,'name',type(error).__name__),code=getattr(error,'code',None),message=getattr(error,'message',str(error))))
            prompts={section['name']:section['text'](dict(scope=None)) for section in sections};hidden.add('edit');without_edit={section['name']:section['text'](dict(scope=None)) for section in sections}
            rows.append(dict(name=case['name'],result=result,calls=calls,observations=effects,prompts=prompts,withoutEdit=without_edit,call=definition['presentCall'](arguments),definition=dict(name=definition['name'],description=definition['description'],parameters=definition['parameters'],outputSchema=definition['output']['schema'])))
        finally:await ctx.fiber.dispose()
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus(),ensure_ascii=False),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_file_consumers.mts','Actual current text tool definitions and callbacks over a controlled filesystem with deliberately different display/process paths; exact schemas, prompts/scoped guidance, typed JS validation, read streaming/window routing, mutation versions/observations, canonical diff metadata and replay.',[Path(__file__).resolve(),ROOT/'dsh/fs/tool_read.py',ROOT/'dsh/fs/tool_fs_mutation.py',ROOT/'dsh/fs/tools_current.py'],prepare=prepare)
