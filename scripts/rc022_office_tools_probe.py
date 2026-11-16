"""Compare actual Office tool callbacks and activation against the fixed Source."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

CASES=['render','convert','recalculate','routed','text-model','no-store','no-llm','no-kit','no-agent','missing','directory','changed','too-large','busy','unavailable','oversized','gif','scaled','remote','owner-error','no-owner','invalid-format','invalid-page','unknown','header','failed-skill','wrong-skill','invalid-skill','message','stale-message']


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.office.errors import OfficeKitError
    from dsh.office.tools import CurrentToolOffice
    from dsh.subagent.errors import SubagentError
    rows=[]
    class Agent:pass
    for name in CASES:
        ctx=Context();calls=[];definitions=[];conditions=[];agent=Agent();session=Agent();session.id='session'
        session.requestHeader=lambda:dict(config=dict(provider='route',model='vision') if name=='routed' else {},tools=[dict(name='office_convert')] if name=='header' else [])
        agent.session=session;agent.options=dict(provider='base',model='base-model');signal=NEVER_ABORTED;count=0
        async def directory(*_):calls.append('directory');return 'C:/working'
        async def resolve(path,options):calls.append(dict(resolve=path,cwd=options['cwd']));return NS(displayPath='C:/display/report.docx')
        async def stat(*_):
            nonlocal count
            count+=1;calls.append('stat')
            return None if name=='missing' else NS(type='directory' if name=='directory' else 'file',version='v2' if name=='changed' and count>1 else 'v1',size=4)
        async def one(target,options,signal):calls.append(dict(range=options));return b'P'
        async def read(target,signal,maximum):
            calls.append(dict(read=maximum))
            if name=='too-large':
                error=RuntimeError('large');error.code='FS_TOO_LARGE';raise error
            return b'PK12'
        async def route(provider,model,signal):calls.append(dict(route=[provider,model]));return dict(inputModalities=['text'] if name=='text-model' else ['image'])
        async def save(inputs):
            calls.append(dict(save=[dict(name=item['name'],mediaType=item['mediaType'],bytes=len(item['data'])) for item in inputs]))
            return [dict(attachmentId='ref',mediaType='image/gif' if name=='gif' else 'image/webp' if name=='scaled' else 'image/png',bytes=8,width=2,height=3,**(dict(originalDimensions=dict(width=4,height=6)) if name=='scaled' else {}))]
        async def operation(request,signal):
            source=request['source'];calls.append(dict(request={key:value for key,value in request.items() if key!='source'},source={key:value for key,value in source.items() if key!='read'}))
            result=await source['read'](signal,20);calls.append(dict(sourceBytes=list(result['bytes']),version=result['version']))
            if name in ('busy','unavailable'):raise OfficeKitError(name,'engine failure')
            if kind=='render':return dict(images=[dict(png=bytes(11 if name=='oversized' else 8),page=1)],pageCount=1,dpi=96,missingFonts=['Font'])
            return dict(path='C:/store/output.txt',bytes=4,pageCount=2,missingFonts=[])
        def root(agent):
            calls.append('owner')
            if name=='owner-error':raise SubagentError('not owned','UNAUTHORIZED')
            return NS(session=NS(id='root'))
        ctx.set_service('tools',NS(register=lambda definition,options:(definitions.append(definition),conditions.append(options['when']))))
        ctx.set_service('agents',NS(get=lambda _:agent));ctx.set_service('workingDirectory',NS(ensure=directory))
        ctx.set_service('fs',NS(resolve=resolve,stat=stat,readByteRange=one,readBytes=read,processPath=lambda _:'C:/canonical/report.docx',processPathFromHostPath=lambda path:None if name=='remote' else path))
        if name!='no-kit':ctx.set_service('officeKit',NS(outputDirectory='C:/store',renderImages=operation,convertTo=operation,recalculate=operation))
        if name!='no-llm':ctx.set_service('llm',NS(resolveModelInfo=route))
        if name!='no-store':ctx.set_service('attachments',NS(imageLimits=dict(maxImagesPerMessage=3,maxImagePixels=100,maxImageDimension=10,maxMessageImageBytes=50,maxImageBytes=10),saveImages=save,isAttachmentError=lambda _:False))
        if name!='no-owner':ctx.set_service('subagents',NS(rootOf=root))
        plugin=CurrentToolOffice();plugin.apply(ctx);kind='recalculate' if name=='recalculate' else 'convert' if name in ('convert','remote','owner-error','no-owner','invalid-format') else 'render'
        definition=next(item for item in definitions if item['name']=='office_'+kind);when=conditions[0];before=when(dict(agent=agent))
        if name in ('message','stale-message'):
            ctx.emit('session/event',session if name=='message' else NS(id='session'),dict(type='user/message',data=dict(source=dict(kind='skill-invocation',name='office'))))
        else:ctx.emit('tools/result',NS(agent=agent,name='skill',arguments=dict(name=[] if name=='invalid-skill' else 'other' if name=='wrong-skill' else 'office')),NS(isError=name=='failed-skill'))
        after=when(dict(agent=agent));args=dict(input='book.xlsx' if kind=='recalculate' else 'report.docx')
        if kind!='render':args['format']='csv' if name=='invalid-format' else 'xlsx' if kind=='recalculate' else 'txt'
        if name=='invalid-page':args['pages']=[0]
        if name=='unknown':args['unknown']=True
        try:
            value=await definition['execute'](args,NS(agent=None if name=='no-agent' else agent,signal=signal));result=dict(value=value,content=definition['output']['render'](args,value),meta=definition['output']['presentationMeta'](args,value))
        except Exception as error:result=dict(error=dict(message=getattr(error,'message',str(error)),code=getattr(error,'code',None)))
        ctx.emit('agent/disposed',dict(agent=agent));disposed=when(dict(agent=agent))
        rows.append(dict(name=name,before=before,after=after,disposed=disposed,result=result,calls=calls,present=definition['presentCall'](args),concurrent=definition['isConcurrencySafe'](args)))
        await ctx.fiber.dispose()
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(CASES),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_office_tools.mts','Actual original tool-office callbacks, activation events/header persistence, one-byte authorization, deferred bounded versioned reads, model route, normalized image refs, owner fallback, remote output gate and precise errors.',[Path(__file__).resolve(),ROOT/'dsh/office/tools.py',ROOT/'dsh/office/tool_definitions.json'],prepare=prepare)
