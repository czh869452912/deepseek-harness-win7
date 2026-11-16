"""Pure Messages requests, signatures and streaming event transitions against Source."""
import base64
import copy
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    def text(value): return dict(type='text',text=value)
    def message(role,content,**extra):
        return dict(role=role,content=content,source=dict(kind='model',provider='deepseek-official',model='m') if role=='assistant' else dict(kind='user'),**extra)
    def tool(call_id='a',arguments='{}'): return dict(type='tool-call',id=call_id,name='read',arguments=arguments)
    user=message('user',[text('hello')]);assistant=message('assistant',[text('answer')])
    result=message('tool',[text('result')],toolCallId='a',isError=False)
    histories=[[],[user],[message('user',[])],[message('assistant',[text('')])],
        [message('system',[text('initial')]),user,message('system',[text('next')]),assistant],
        [user,message('system',[text('')]),assistant],[user,message('developer',[text('patch')]),assistant],
        [message('developer',[text('patch')]),assistant],[user,message('developer',[dict(type='tool-addition',toolName='read'),dict(type='tool-removal',toolName='write')]),assistant],
        [user,assistant,user,assistant],[user,message('assistant',[tool()]),result],
        [user,message('assistant',[tool()])],[result],[user,message('assistant',[tool(),tool()]),result],
        [user,message('assistant',[tool()]),user],[user,message('assistant',[tool()]),message('tool',[],toolCallId='a')],
        [user,message('assistant',[tool('a'),tool('b')]),message('user',[text('interspersed')]),result,message('tool',[text('B')],toolCallId='b')]]
    for raw in ['bad','[]','null','1','true','{"2":2,"1":1}','{"path":"a"}']:
        histories.append([user,message('assistant',[tool(arguments=raw)]),result])
    for role in ('user','assistant','system','developer'):
        for content in [[dict(type='file')],[dict(type='reasoning',text='thought')],[dict(type='tool-addition',toolName='read')]]:
            histories.append([user,message(role,content)])
    serial=[]
    configs=[dict(models=[dict(id='m')]),dict(models=[dict(id='m',systemPromptUpdate='in-history')])]
    for config in configs:
        for history in histories:
            for options in [{},dict(reasoningEffort='off'),dict(reasoningEffort='bad'),dict(temperature=0,stop=['END'],maxTokens=32,
                tools=[dict(name='read',description='Read',parameters=dict(type='object'),deferLoading=True)])]:
                serial.append(dict(config=config,history=history,options=options))
    for config in [dict(thinking='disabled'),dict(reasoningEffort='low'),dict(reasoningEffort='max')]:
        serial.append(dict(config=config,history=[user],options={}))
    replay=message('assistant',[dict(type='reasoning',text='thought'),text('answer')])
    envelope=dict(response=dict(kind='deepseek-messages',version=1,model='m'),blocks=[dict(type='reasoning',signature='signed'),dict(type='text')])
    replays=[None,{},dict(response=None),envelope]
    for path,value in [('version',True),('version',2),('kind','other'),('model','other')]:
        entry=copy.deepcopy(envelope);entry['response'][path]=value;replays.append(entry)
    for blocks in [None,[],[None,dict(type='text')],[dict(type='text'),dict(type='text')],[dict(type='reasoning',signature=1),dict(type='text')]]:
        entry=copy.deepcopy(envelope);entry['blocks']=blocks;replays.append(entry)
    for native in replays:
        entry=copy.deepcopy(replay);entry['source']['replayState']=native
        serial.append(dict(config={},history=[user,entry],options={}))
    image_id='sha256:'+'a'*64
    ref=dict(attachmentId=image_id,name='input "image"',mediaType='image/png',width=20,height=30,bytes=4)
    for files in [None,{}, {image_id:'file-a'}]:
        for access in [None,dict(readonlyPath='C:\\images\\input.png')]:
            serial.append(dict(config={},history=[message('user',[dict(type='image',attachment=ref)])],options={},
                images={image_id:dict(mediaType='image/jpeg',width=10,height=20,base64='AAECAw==')},fileIds=files,access=access))
    serial.append(dict(config={},history=[message('user',[dict(type='image',attachment=ref)])],options={}))
    start=dict(type='message_start',message=dict(usage=dict(input_tokens=12,output_tokens=1,cache_read_input_tokens=3)))
    begin=dict(type='content_block_start',index=4,content_block=dict(type='text',text='initial'))
    delta=dict(type='content_block_delta',index=4,delta=dict(type='text_delta',text=' plus'))
    stop=dict(type='content_block_stop',index=4)
    end=[dict(type='message_delta',delta=dict(stop_reason='end_turn'),usage=dict(output_tokens=5)),dict(type='message_stop')]
    valid=[start,begin,delta,stop,*end]
    streams=[valid,[],[start],*[valid[:index] for index in range(1,len(valid))],
        [start,start], [begin], [start,begin,begin], [start,delta], [start,stop], [start,begin,stop,stop],
        [start,dict(type='content_block_start',index=-1,content_block=dict(type='text',text=''))],
        [start,dict(type='message_delta',delta=dict(stop_reason='end_turn')),begin],
        [start,dict(type='message_stop')],[start,*end],
        [dict(type='ping'),*valid,dict(type='message_stop')]]
    for key in ['input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens']:
        for value in [None,False,-1,.5,0,9007199254740991,9007199254740992]:
            entry=copy.deepcopy(valid);entry[0]['message']['usage'][key]=value;streams.append(entry)
    for block in [dict(type='thinking',thinking='initial',signature=''),dict(type='tool_use',id='a',name='read',input={}),
                  dict(type='image'),dict(type='text',text=None),dict(type='tool_use',id='',name='read',input={})]:
        kind=block['type']
        for end_reason in ['end_turn','tool_use','max_tokens','unknown']:
            sequence=[start,dict(type='content_block_start',index=7,content_block=block)]
            if kind=='thinking': sequence.extend([dict(type='content_block_delta',index=7,delta=dict(type='thinking_delta',thinking=' thought')),dict(type='content_block_delta',index=7,delta=dict(type='signature_delta',signature='sig'))])
            if kind=='tool_use': sequence.append(dict(type='content_block_delta',index=7,delta=dict(type='input_json_delta',partial_json='{"path":')))
            sequence.extend([dict(type='content_block_stop',index=7),dict(type='message_delta',delta=dict(stop_reason=end_reason)),dict(type='message_stop')]);streams.append(sequence)
    for delta_value in [None,{},dict(type='thinking_delta',thinking='no'),dict(type='text_delta',text=None)]:
        entry=copy.deepcopy(valid);entry[2]['delta']=delta_value;streams.append(entry)
    info=[]
    for config in [{},dict(thinking='disabled'),dict(reasoningEffort='off'),dict(reasoningEffort='max'),dict(models=[dict(id='m',maxTokens=32,contextWindow=512,toolUpdate='in-history')])]:
        for model in ['deepseek-flash','deepseek-v4-pro','m','unknown']: info.append(dict(config=config,model=model))
    return dict(serial=serial,streams=streams,info=info,urls=['https://api.deepseek.com/anthropic','http://host/v1','http://host/v1///','http://host/V1','http:\\host\\v1'])


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


async def observe():
    from dsh.llm.deepseek_config_current import resolveAdapterOptions
    from dsh.llm.deepseek_messages_serialize import serialize
    from dsh.llm.deepseek_messages_translate import translate
    from dsh.llm.deepseek_model_info_current import modelInfo,messagesApiRoot
    from dsh.llm.assembler import BlockAssembler
    from dsh.core.session.json import UNDEFINED
    rows=[];inputs=cases()
    for index,case in enumerate(inputs['serial']):
        degraded=[];history=copy.deepcopy(case['history']);before=copy.deepcopy(history)
        images={key:dict(value,data=base64.b64decode(value['base64'])) for key,value in case.get('images',{}).items()}
        try:
            result=dict(value=serialize(dict(provider='deepseek-official',model='m',system='base',**case['options']),resolveAdapterOptions(case['config']),history,images,lambda _:case.get('access'),degraded.append,case.get('fileIds')))
        except Exception as error: result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        rows.append(dict(kind='serialize',index=index,degraded=degraded,unchanged=history==before,**result))
    for index,sequence in enumerate(inputs['streams']):
        async def events():
            for event in copy.deepcopy(sequence): yield event
        chunks=[]
        try:
            async for chunk in translate(events(),'m'): chunks.append(chunk)
            result={}
        except Exception as error: result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        assembler=BlockAssembler()
        for chunk in chunks: assembler.push(chunk)
        assembled=dict(blocks=assembler.blocks(),replayState=None if assembler.replayState is UNDEFINED else assembler.replayState)
        rows.append(dict(kind='translate',index=index,chunks=chunks,assembled=assembled,**result))
    rows.extend(dict(kind='info',index=index,value=modelInfo(resolveAdapterOptions(case['config']),'deepseek-official',case['model'])) for index,case in enumerate(inputs['info']))
    rows.extend(dict(kind='root',index=index,value=messagesApiRoot(url)) for index,url in enumerate(inputs['urls']))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_messages_wire.mts','Original/native Messages request serialization and event state machine, durable replay degradation and signatures, '
        'ordered developer/tool changes and system updates, immediate tool settlement, inline/file image handles, reasoning policy, cumulative usage and malformed/truncated response settlement. '
        'Also current model metadata and Messages root policy. No HTTP or provider lifecycle activation claim.',
        [Path(__file__).resolve()]+[ROOT/'dsh/llm'/name for name in ['deepseek_messages_replay.py','deepseek_messages_serialize.py','deepseek_messages_translate.py','deepseek_model_info_current.py']],prepare=prepare)
