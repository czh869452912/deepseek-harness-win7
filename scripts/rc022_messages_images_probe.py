"""V4.1 geometry, occurrence pricing and Messages image admission against Source."""
import copy
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rng=random.Random(2203)
    edges=[1,2,13,14,15,41,42,43,511,512,543,544,545,1024,4095,4096,4097,8192,1000000]
    geometry=[[w,h] for w in edges for h in edges]
    geometry += [[rng.randint(1,8192),rng.randint(1,8192)] for _ in range(500)]
    ref=dict(attachmentId='sha256:'+'a'*64,mediaType='image/png',width=3000,height=2000,bytes=5000,name='图像 "one"')
    other=dict(ref,attachmentId='sha256:'+'b'*64,width=1,height=8192,name='long')
    blocks=[dict(type='image',attachment=ref),dict(type='image',attachment=dict(ref,name='same bytes, new name')),
        dict(type='image',attachment=other),dict(type='image',attachment=ref,offloaded=True)]
    pricing=[]
    for identifier in ('m','text','unknown'):
        for budget in (None,'low',1,500000,64000000):
            for access in (None,dict(readonlyPath='C:\\fixture\\图像.png')):
                model=dict(id='m',inputModalities=['text','image'])
                if budget is not None:model['imagePixelBudget']=budget
                pricing.append(dict(model=model,id=identifier,access=access,images=blocks))
    admission=[]
    for lengths in ([],[0],[1,2,3],[12,12,12,12],[100,1,1,1],[1,1,1,100]):
        for representation in ('raw','base64'):
            for max_bytes in (0,1,12,24,102,1000):
                for byte_quantum in (1,12):
                    admission.append(dict(lengths=lengths,budget=dict(representation=representation,maxBytes=max_bytes,maxImages=3,byteQuantum=byte_quantum,countQuantum=2)))
    preparation=[]
    base=dict(models=[dict(id='m',inputModalities=['text','image'])])
    histories=[[],[dict(role='user',content=[dict(type='text',text='hello')])],
        [dict(role='user',content=blocks)], [dict(role='user',content=[blocks[-1]])]]
    # Keep roles separate: tool result content is a top-level typed message.
    histories=histories[:4]+[[dict(role=role,content=[blocks[0]])] for role in ('system','assistant','developer','tool')]
    histories += [[dict(role='user',content=[blocks[0]]),dict(role='tool',content=[blocks[1],blocks[2]])]]
    for history in histories:
        for provider in (True,False):
            for model in ('m','unknown'):
                for budget in ({},dict(maxRequestFilesBytes=2,imageOffloadByteQuantum=1),dict(maxInlineRequestImageBytes=2,inlineImageOffloadByteQuantum=1),dict(maxImagesPerRequest=1,imageOffloadCountQuantum=1)):
                    preparation.append(dict(history=history,attachments=provider,model=model,config=dict(base,**budget),access=dict(readonlyPath='/fixture/image.png')))
    return dict(geometry=geometry,pricing=pricing,admission=admission,preparation=preparation)


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


async def observe():
    from dsh.llm.deepseek_image_pricing_current import deepSeekImageTokens,deepSeekRequestImageDimensions,resolveRequestImageTarget,imagePricing
    from dsh.llm.image_content_current import requiredImageOffload
    from dsh.llm.deepseek_messages_images import prepareImages,inlineImages,prepareFileIds
    from dsh.llm.deepseek_config_current import resolveAdapterOptions
    rows=[];input=cases()
    for index,(width,height) in enumerate(input['geometry']):
        try:result=dict(tokens=deepSeekImageTokens(width,height),dimensions=deepSeekRequestImageDimensions(width,height),
            target=resolveRequestImageTarget({},dict(width=width,height=height)))
        except Exception as error:result=dict(error=str(error))
        rows.append(dict(kind='geometry',index=index,**result))
    for index,case in enumerate(input['pricing']):
        connection=dict(models=[case['model'],dict(id='text')])
        value=imagePricing(connection,case['id'],lambda ref:case['access']).priceImages(case['images'])
        rows.append(dict(kind='pricing',index=index,value=value))
    for index,case in enumerate(input['admission']):
        content=[dict(type='image',attachment=dict(bytes=size)) for size in case['lengths']]
        count=requiredImageOffload([dict(content=content)],case['budget'],lambda block:block['attachment']['bytes'])
        rows.append(dict(kind='admission',index=index,count=count))
    for index,case in enumerate(input['preparation']):
        calls=[];occurrences=[];history=copy.deepcopy(case['history']);before=copy.deepcopy(history)
        async def read(ref,target,signal):
            calls.append(dict(ref=ref,target=target))
            return dict(attachment=ref,bytes=3 if str(ref['attachmentId'])[7]=='a' else 12,width=target['width'],height=target['height'])
        async def resolve(version,location):
            occurrences.append(dict(id=version['attachment']['attachmentId'],location=location))
            return 'file-'+str(len(occurrences))
        try:
            config=resolveAdapterOptions(case['config'])
            value=await prepareImages(history,config,case['model'],SimpleNamespace(readImageRequest=read) if case['attachments'] else None,lambda ref:case['access'],None)
            ids=await prepareFileIds(value['messages'],value['versions'],SimpleNamespace(resolve=resolve))
            result=dict(messages=value['messages'],versions=value['versions'],ids=ids)
            try:result['inline']=inlineImages(value['messages'],value['versions'],config)
            except Exception as error:result['inlineError']=error.failure
        except Exception as error:result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None),failure=getattr(error,'failure',None))
        rows.append(dict(kind='preparation',index=index,calls=calls,occurrences=occurrences,unchanged=history==before,**result))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_messages_images.mts','Fixed Source V4.1 image grid, target dimensions, per-occurrence offload-aware pricing, raw/base64 budget admission, retained-version deduplication and Files occurrence locations.',
        [Path(__file__).resolve(),ROOT/'dsh/llm/image_content_current.py',ROOT/'dsh/llm/deepseek_image_pricing_current.py',ROOT/'dsh/llm/deepseek_messages_images.py'],prepare=prepare)
