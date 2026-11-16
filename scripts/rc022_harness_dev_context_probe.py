"""Compare frozen admitted prompt folding and dynamic context against Source."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    from dsh.context.harness_dev_current import CONSTANTS
    source=CONSTANTS['LEGACY_SOURCE'];web=CONSTANTS['LEGACY_WEB_SURFACE']
    legacy=source['prefix']+'C:/old {{checkout}}'+source['suffix']+'\n\n'+web['prefix']+'http://old:1234/'+web['suffix']
    def event(content):return dict(type='system/message',data=dict(message=dict(content=content)))
    text=lambda value:dict(type='text',text=value)
    return [dict(name='unrelated',event=dict(type='user/message',data={})),dict(name='legacy',event=event([text(legacy)])),
        dict(name='empty-preserves',event=event([text('')])),dict(name='multiple-preserves',event=event([text('new'),text('ignored')])),
        dict(name='nontext-preserves',event=event([dict(type='image')])),dict(name='zero-preserves',event=event([])),
        dict(name='newline-source',event=event([text(source['prefix']+'C:/bad\npath'+source['suffix'])])),
        dict(name='source-only',event=event([text(source['prefix']+'D:/other'+source['suffix'])])),
        dict(name='missing-suffix',event=event([text(source['prefix']+'D:/incomplete')])),dict(name='plain-clears',event=event([text('plain prompt')]))]


async def observe():
    from dsh.context.harness_dev_current import CurrentHarnessDevContext, SOURCE_ROOT
    from dsh.cordis.json_text import stringify_json
    state=dict(source=None,web=None);sections=[];contexts=[];rows=[];captured=[];url=['http://new:8123/']
    async def register(value):captured.append(value);return NS(stateOf=lambda _:state)
    prompt=NS(section=sections.append,context=contexts.append,getSectionOrder=lambda key:key,getContextOrder=lambda key:key)
    ctx=NS(webApp=NS(getAdvertisedUrl=lambda:url[0]),sessionProjections=NS(register=register),systemPrompt=prompt)
    await CurrentHarnessDevContext.apply(None,ctx)
    def snapshot(name):
        resolved=[]
        for row in contexts:
            text=row['text']() if callable(row['text']) else row['text']
            resolved.append(dict(row,text=text.replace(stringify_json(SOURCE_ROOT),'"<implementation-root>"')))
        rows.append(dict(name=name,state=state,sections=[dict(row,text=row['text'](dict(agent=NS(session={})))) for row in sections],contexts=resolved))
    snapshot('initial')
    for item in corpus():state=captured[0]['apply'](state,item['event']);snapshot(item['name'])
    url[0]='http://changed:9123/';snapshot('url-changed')
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_harness_dev_context.mts','Actual original Host callbacks: admitted legacy paragraphs, ignored empty/multiblock/nontext versions, malformed/newline paragraphs, clearing, dynamic URL and stable prompt/context text. Only the implementation-root runtime value is normalized because the Python host has its own checkout.',[Path(__file__).resolve(),ROOT/'dsh/context/harness_dev_current.py',ROOT/'dsh/context/harness_dev_text_current.json'],prepare=prepare)
