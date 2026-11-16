"""Skill-admitted Office tools using current source authority and stored image refs."""
import copy
import json
import os
from pathlib import Path
import re
from weakref import WeakSet

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.cordis.json_text import stringify_json
from dsh.subagent.errors import SubagentError
from dsh.typert.stores import field
from .content import render_file_content,render_images_content
from .errors import OfficeKitError
from .formats import check_parameter_names,check_render_arguments,check_conversion_arguments,input_family,extension_of

DEFAULTS=dict(activationSkills=['office','office-docx','office-xlsx','office-pptx'],maxImages=20,maxImagePixels=8388608,maxImageDimension=8192,maxImageBytes=33554432)


def office_failure(verb,path,error):
    if not isinstance(error,OfficeKitError):return error
    hint=' Tell the user this operation is unavailable, or retry later if the cause may be temporary; do not substitute system soffice, npx, or another converter.' if error.code=='unavailable' else ' Retry after other document operations finish.' if error.code=='busy' else ' Select fewer pages, a smaller range, or a lower dpi.' if error.code=='output-too-large' and verb=='render' else ''
    result=RuntimeError('cannot {} "{}": {}{}'.format(verb,path,error.message,hint));result.cause=error;return result


class CurrentToolOffice(Plugin):
    id='@deepseek-ai/dsh-tool-office';name='tool-office';inject=['tools','fs','workingDirectory','agents']
    Config=z.object(dict(activationSkills=z.array(z.string().pattern(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')).min(1).default(DEFAULTS['activationSkills']),
        maxImages=z.natural().min(1).max(10000).default(20),maxImagePixels=z.natural().min(1).max(16777216).default(8388608),
        maxImageDimension=z.natural().min(1).max(16777216).default(8192),maxImageBytes=z.natural().min(1).max(9007199254740991).default(33554432)))

    def apply(self,ctx):
        self.ctx=ctx;self.caps=dict(DEFAULTS,**self.config);marked=WeakSet();skills=set(self.caps['activationSkills'])
        def result(execution,outcome):
            agent=field(execution,'agent');args=field(execution,'arguments')
            if agent is not None and field(execution,'name')=='skill' and not field(outcome,'isError') and isinstance(args,dict) and isinstance(args.get('name'),str) and args['name'] in skills:marked.add(agent)
        def event(session,event):
            source=field(field(event,'data'),'source')
            if field(event,'type')=='user/message' and field(source,'kind')=='skill-invocation' and field(source,'name') in skills:
                agent=ctx.get('agents').get(field(session,'id'))
                if agent is not None and field(agent,'session') is session:marked.add(agent)
        ctx.on('tools/result',result);ctx.on('session/event',event);ctx.on('agent/disposed',lambda event:marked.discard(field(event,'agent')))
        def when(context):
            agent=field(context,'agent');header=agent.session.requestHeader()
            return agent in marked or any(field(tool,'name') in ('office_render','office_convert','office_recalculate') for tool in field(header,'tools',[]) or [])
        with Path(__file__).with_name('tool_definitions.json').open('r',encoding='utf-8') as stream:definitions=json.load(stream)
        for definition in definitions:
            definition=copy.deepcopy(definition);name=definition['name'];operation=name[len('office_'):]
            async def execute(args,execution,operation=operation,name=name):
                check_parameter_names(name,args);family=input_family(operation,args['input'])
                if operation=='render':check_render_arguments(args,family)
                if operation=='convert':check_conversion_arguments(args,family)
                agent,kit,target,source=await self.prepare_input(execution,operation,args['input'])
                if operation=='render':return await self.render(kit,agent,execution.signal,args,target,source)
                return await self.convert_file(kit,agent,execution.signal,operation,args,target,source)
            def present(args,operation=operation):
                title=('Render '+args['input']) if operation=='render' else ('Convert '+args['input']+' to '+args['format']) if operation=='convert' else ('Recalculate '+args['input'])
                return dict(card='generic',title=title,kind='read' if operation=='render' else 'other',locations=[dict(path=args['input'])])
            definition.update(execute=execute,presentCall=present,isConcurrencySafe=lambda args,operation=operation:operation=='render')
            definition['output'].update(render=lambda args,value,operation=operation:(render_images_content if operation=='render' else render_file_content)(value),
                presentationMeta=lambda args,value,operation=operation:dict(path=value['path']) if operation=='render' else dict(path=value['path'],file=value['file']))
            ctx.get('tools').register(definition,dict(when=when))

    async def unchanged(self,target,info,signal):
        current=await self.ctx.get('fs').stat(target,signal)
        if field(current,'type')!='file' or field(current,'version')!=field(info,'version'):raise OfficeKitError('source-changed','The source changed.')

    async def prepare_input(self,execution,operation,input):
        agent=field(execution,'agent');signal=execution.signal;ctx=self.ctx
        if agent is None:raise RuntimeError('cannot {} "{}": Office tools run only in an Agent step'.format(operation,input))
        kit=ctx.get('officeKit')
        if kit is None:raise office_failure(operation,input,OfficeKitError('unavailable','The document converter is unavailable.'))
        cwd=await ctx.get('workingDirectory').ensure(agent,signal);fs=ctx.get('fs');target=await fs.resolve(input,dict(cwd=cwd,signal=signal));info=await fs.stat(target,signal)
        if info is None:raise RuntimeError('cannot read "{}": not found'.format(field(target,'displayPath')))
        if field(info,'type')!='file':raise RuntimeError('cannot read "{}": not a regular file'.format(field(target,'displayPath')))
        try:
            await fs.readByteRange(target,dict(offset=0,length=1),signal);await self.unchanged(target,info,signal)
        except Exception as error:raise office_failure(operation,field(target,'displayPath'),error)
        async def read(upstream,maximum):
            await self.unchanged(target,info,upstream)
            try:data=await fs.readBytes(target,upstream,maximum)
            except Exception as cause:
                if getattr(cause,'code',None)=='FS_TOO_LARGE':raise OfficeKitError('input-too-large','The source exceeds the reserved byte capacity.',cause=cause) from None
                raise
            await self.unchanged(target,info,upstream);return dict(bytes=data,version=field(info,'version'))
        source=dict(key=stringify_json([agent.session.id,fs.processPath(target)]),version=field(info,'version'),read=read)
        if field(info,'size') is not None:source['bytes']=field(info,'size')
        return agent,kit,target,source

    async def render(self,kit,agent,signal,args,target,source):
        ctx=self.ctx;path=ctx.get('fs').processPath(target);display=field(target,'displayPath');attachments=ctx.get('attachments')
        if attachments is None:raise RuntimeError('cannot render "{}": no attachment service is mounted'.format(display))
        llm=ctx.get('llm');header=field(agent.session.requestHeader(),'config',{}) or {};options=agent.options
        model=field(header,'model');provider=field(header,'provider')
        if model is None:model=field(options,'model')
        if provider is None:provider=field(options,'provider')
        if llm is None or provider is None or model is None:raise RuntimeError('cannot render "{}": the current model route could not be resolved'.format(display))
        info=await llm.resolveModelInfo(provider,model,signal)
        if 'image' not in (field(info,'inputModalities',[]) or []):raise RuntimeError('cannot render "{}": model "{}" does not accept images'.format(display,model))
        limits=attachments.imageLimits;request=dict(extension=extension_of(args['input']),source=source,
            maxImages=min(self.caps['maxImages'],limits['maxImagesPerMessage']),maxPixels=min(self.caps['maxImagePixels'],limits['maxImagePixels']),
            maxDimension=min(self.caps['maxImageDimension'],limits['maxImageDimension']),maxBytes=min(self.caps['maxImageBytes'],limits['maxMessageImageBytes']))
        for key in ('pages','sheet','range','dpi'):
            if key in args:request[key]=args[key]
        try:result=await kit.renderImages(request,signal)
        except Exception as error:raise office_failure('render',display,error)
        if any(len(image['png'])>limits['maxImageBytes'] for image in result['images']):raise RuntimeError('cannot render "{}": an image exceeds the {}-byte image limit; select a smaller range or a lower dpi'.format(display,limits['maxImageBytes']))
        stem=os.path.basename(display)
        try:refs=await attachments.saveImages([dict(data=image['png'],mediaType='image/png',name='{}-{}.png'.format(stem,index+1)) for index,image in enumerate(result['images'])])
        except Exception as error:
            if not attachments.isAttachmentError(error):raise
            failure=RuntimeError('cannot render "{}": {}'.format(display,getattr(error,'message',str(error))));failure.cause=error;raise failure from None
        images=[]
        for index,image in enumerate(result['images']):
            ref=refs[index]
            if ref['mediaType']=='image/gif':raise RuntimeError('cannot render "{}": the attachment service stored a rendered PNG as GIF'.format(display))
            value={key:image[key] for key in ('page','sheet','range') if key in image};value.update({key:ref[key] for key in ('attachmentId','mediaType','bytes','width','height')})
            if 'originalDimensions' in ref:value['originalDimensions']=dict(ref['originalDimensions'])
            images.append(value)
        return dict(operation='render',path=path,pageCount=result['pageCount'],dpi=result['dpi'],missingFonts=result['missingFonts'],images=images)

    def output_owner(self,agent):
        subagents=self.ctx.get('subagents')
        if subagents is None:return agent.session.id
        try:return subagents.rootOf(agent).session.id
        except SubagentError as error:
            if error.code=='UNAUTHORIZED':return agent.session.id
            raise

    async def convert_file(self,kit,agent,signal,operation,args,target,source):
        fs=self.ctx.get('fs');display=field(target,'displayPath')
        if fs.processPathFromHostPath(kit.outputDirectory) is None:raise RuntimeError('cannot {} "{}": converted files are not available when the workspace is on a remote host'.format(operation,display))
        format=args['format'];stem=re.sub(r'\.[^.]*$','',os.path.basename(display));request=dict(extension=extension_of(args['input']),format=format,source=source,output=dict(owner=self.output_owner(agent),name=stem+'.'+format))
        if operation=='convert' and 'sheet' in args:request['sheet']=args['sheet']
        try:result=await (kit.convertTo if operation=='convert' else kit.recalculate)(request,signal)
        except Exception as error:raise office_failure(operation,display,error)
        value=dict(operation=operation,path=fs.processPath(target),file=fs.processPathFromHostPath(result['path']),format=format,bytes=result['bytes'],missingFonts=result['missingFonts'])
        if 'pageCount' in result:value['pageCount']=result['pageCount']
        return value
