"""Optional scoped read-only market listing over the Host pluginMarket service."""
import asyncio
import copy
import json
import math
from pathlib import Path

from dsh.cordis.awaiting import await_callback_result,start_coroutine
from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.cordis.text import trim_js
from dsh.util_time_calendar import calendar_date

DESCRIPTOR=json.loads((Path(__file__).parent/'plugin_market_tools.json').read_text(encoding='utf-8'))
MISSING=object()


def english(text=MISSING):
    value=text.get('en',MISSING) if isinstance(text,dict) else text
    if value is MISSING:return MISSING
    raw=value.encode('utf-16-le','surrogatepass')
    return value if len(raw)<=600 else raw[:600].decode('utf-16-le','surrogatepass')+'…'


def page_of(args):
    offset=args.get('offset');limit=args.get('limit');offset=0 if offset is None else offset;limit=25 if limit is None else limit
    if any(type(value) not in (int,float) or not math.isfinite(value) or int(value)!=value for value in (offset,limit)) or offset<0 or not 1<=limit<=100:
        raise RuntimeError('offset must be a non-negative integer and limit must be an integer from 1 to 100')
    return int(offset),int(limit)


def version_result(version):
    timestamp=version['publishTimestamp']*1000
    if not math.isfinite(timestamp) or abs(timestamp)>8640000000000000:raise ValueError('Invalid time value')
    epoch=math.trunc(timestamp);year,month,day=calendar_date(epoch//86400000);clock=epoch%86400000
    year_text='%04d'%year if 0<=year<=9999 else '%+07d'%year
    published='%s-%02d-%02dT%02d:%02d:%02d.%03dZ'%(year_text,month,day,clock//3600000,clock//60000%60,clock//1000%60,clock%1000)
    install=dict(target=version['install']['spec'])
    if 'registry' in version['install']:install['registry']=version['install']['registry']
    return dict(version=version['version'],published=published,compatibility=version['compatibility'],install=install)


async def until_aborted(promise,signal):
    async def read():return await await_callback_result(promise)
    shared=start_coroutine(read());shared=asyncio.ensure_future(shared)
    def consume(task):
        if not task.cancelled():task.exception()
    shared.add_done_callback(consume)
    waiter=asyncio.get_running_loop().create_future()
    def abort(*_):
        if not waiter.done():waiter.set_exception(signal.reason if isinstance(signal.reason,Exception) else RuntimeError('Aborted'))
    def settle(task):
        if waiter.done():return
        if task.cancelled():waiter.cancel()
        elif task.exception() is not None:waiter.set_exception(task.exception())
        else:waiter.set_result(task.result())
    signal.addEventListener('abort',abort,dict(once=True));shared.add_done_callback(settle)
    try:return await waiter
    finally:signal.removeEventListener('abort',abort)


class CurrentPluginMarketTools(Plugin):
    inject=['tools']

    def apply(self,ctx):ctx.inject(['pluginMarket'],self.register)

    def register(self,ctx):
        async def execute(args,execution):
            execution.signal.throwIfAborted();market=ctx.pluginMarket;action=args['action']
            if action=='list_indexes':
                indexes=[]
                for index in market.listIndexes():
                    title=english(index.get('title',MISSING));row=dict(url=index['url'],title=None if title is MISSING else title)
                    if 'error' in index:row['error']=index['error']
                    indexes.append(row)
                return stringify_json(dict(indexes=indexes))
            if 'target' not in args:raise RuntimeError('target index URL is required')
            if action=='list_versions' and 'name' not in args:raise RuntimeError('name is required')
            offset,limit=page_of(args)
            if action=='list_plugins':
                text=args.get('query') or ''
                result=await until_aborted(market.search(args['target'],dict(text=text,sort=dict(kind='index' if trim_js(text)=='' else 'relevance'),offset=offset,limit=limit)),execution.signal)
                entries=[]
                for entry in result['entries']:
                    chosen=next((version for version in entry['versions'] if version['version']==entry.get('defaultVersion')),None)
                    title=english(entry.get('title',MISSING));row=dict(name=entry['name'],title=entry['name'] if title is MISSING else title)
                    for key in ('description','author'):
                        value=english(entry.get(key,MISSING))
                        if value is not MISSING:row[key]=value
                    for key in ('homepage','repository'):
                        if key in entry:row[key]=entry[key]
                    if 'category' in entry['metadata']:row['category']=entry['metadata']['category']
                    row.update(labels=entry['metadata']['labels'],sortKeys=entry['metadata']['sortKeys'],installation=entry['installation'],defaultVersion=None if chosen is None else version_result(chosen),versionCount=len(entry['versions']));entries.append(row)
                value={};title=english(result.get('title',MISSING))
                if title is not MISSING:value['index']=title
                value.update(entries=entries,total=result['total'],nextOffset=result['nextOffset']);return stringify_json(value)
            entry=await until_aborted(market.entry(args['target'],args['name']),execution.signal)
            if entry is None:raise RuntimeError('{} is not listed in {}'.format(args['name'],args['target']))
            versions=entry['versions'];selected=versions[offset:offset+limit];next_offset=offset+len(selected)
            return stringify_json(dict(name=entry['name'],defaultVersion=entry.get('defaultVersion'),versions=[version_result(version) for version in selected],total=len(versions),nextOffset=next_offset if next_offset<len(versions) else None))
        definition=copy.deepcopy(DESCRIPTOR['definition']);schema=definition.pop('outputSchema')
        definition.update(execute=execute,output=dict(schema=schema,render=lambda args,value:[dict(type='text',text=value)]),presentCall=lambda args:dict(card='generic',title='Browse plugin indexes',kind='read',rawInput=args))
        ctx.tools.register(definition)
