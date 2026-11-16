"""Compare listing decoding against the unchanged rc022 Source."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    bodies = [None, [], {}, dict(data=None), dict(data=[]), dict(data=[None, 1, '', {}, dict(id='')])]
    def row(**values):
        return dict(id='a', api_capabilities=dict(anthropic_messages={}), **values)
    def add(value): bodies.append(dict(data=[value]))
    add(row())
    bodies.append(dict(data=[row(name='first'), row(name='duplicate'), None, dict(id=0), dict(id=' ')]))
    for key in ('client_requirements', 'client_metadata'):
        for value in (None, 0, False, '', [], {}, {'other':None}, {'deepseek-harness':None},
                      {'deepseek-harness':[]}, {'deepseek-harness':{}}, {'deepseek-harness':{'min_version':None}},
                      {'deepseek-harness':{'min_version':'v0.2.2-rc.3'}}):
            add(row(**{key:value}))
    for key in ('input_modalities', 'output_modalities'):
        for value in (None, False, 'text', [], ['audio'], ['image'], ['text','image','text'], ['image','text'], ['text',None,False]):
            add(row(**{key:value}))
    for key in ('context_window','max_output_tokens'):
        for value in (None, False, True, 0, -1, .5, 1, 1.0, 9007199254740991, 9007199254740992, 10**400, '100'):
            add(row(**{key:value}))
    for value in (None, [], '', {}, dict(anthropic_messages=None), dict(anthropic_messages=[])):
        entry=row();entry['api_capabilities']=value;add(entry)
    for key in ('system_prompt_update','tool_update'):
        for value in (None, False, '', 'leading-only', 'in-history','addition-only', [], {}):
            entry=row();entry['api_capabilities']['anthropic_messages'][key]=value;add(entry)
    texts = ['', ' ', '  New  ', 'a'*12, 'a'*13, '\ufeffNew\ufeff', '\u0085', '\u200b', '\u2066New',
             'a\nb', '\rNew', 'New\t', {'en':'New', 'zh-cn':'新'}, {'zh':'新'}, {'EN':'New'}, {'en':''}, {'en':'New','a':'bad'}]
    tables=json.loads((ROOT/'dsh/resources/model_badge_unicode16.json').read_text(encoding='utf-8'))['tables']
    for ranges in tables.values():
        for start,end in ranges:
            for code in sorted(set([max(0,start-1),start,end,min(0x10ffff,end+1)])):
                texts.extend([chr(code), 'a'+chr(code)])
    clusters=json.loads((ROOT/'tests/fixtures/unicode/grapheme16.json').read_text(encoding='utf-8'))
    texts.extend(''.join(parts)*6 for parts in clusters)
    for text in texts:
        add(row(client_metadata={'deepseek-harness':dict(badge=dict(text=text, tone='info'))}))
    for badge in (None, False, [], {}, dict(text='New',tone='bad'), dict(text='New',tone=None), dict(text={'en':'New','zh-hans':'新'},tone='success')):
        add(row(client_metadata={'deepseek-harness':dict(badge=badge)}))
    return dict(bodies=bodies, urls=['https://api.deepseek.com/anthropic', 'https://User:secret@EXAMPLE.COM:443/v1?q=1',
        'http://127.1:80/other', 'http://[::1]:8042/a', 'https://例子.测试/x', 'http:\\example.com\\v1',
        'ws://host:81/path', 'ftp://host/a', 'broken', 'file:///tmp/x', 'https://host:65536', 'https://0x7f000001/path'])


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


async def observe():
    from dsh.llm.model_listing import parseModelListing,modelListingURL
    rows=[]
    for kind,values,callback in [('body',cases()['bodies'],parseModelListing),('url',cases()['urls'],modelListingURL)]:
        for index,value in enumerate(values):
            try: result=dict(value=callback(value))
            except Exception as error: result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
            rows.append(dict(kind=kind,index=index,**result))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_model_listing.mts','Original/native entry decoder: malformed/duplicate rows, client requirements, '
        'capabilities and capacity bounds, modality order, update modes, localized badge validation including every binary property range edge '
        'and Unicode 16 grapheme conformance sequences. Listing URL origin isolates credentials. HTTP exchange is verified separately.',
        [Path(__file__).resolve(),ROOT/'dsh/llm/model_listing.py',ROOT/'dsh/resources/model_badge_unicode16.json',
         ROOT/'dsh/terminal/grapheme.py',ROOT/'dsh/terminal/unicode16/grapheme.json'],prepare=prepare)
