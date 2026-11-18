"""v3 query consumers over the public stat/list/open handle contract."""
import copy
import math
from functools import cmp_to_key

from dsh.cordis.plugin import Plugin
from dsh.core.session.current import snapshotSessionEvent
from dsh.core.session.current_session import CurrentSession
from dsh.core.session.current_surface import foldSurface
from dsh.core.session.types import SessionHeader
from dsh.session import tracing
from dsh.session.cold_read import readColdSessionLog
from dsh.session.corpus import SessionCorpus
from dsh.session.icu_collation import locale_compare
from dsh.session.observation import error_message, failure_value
from dsh.session.observation_current import CurrentSessionObservationReader
from dsh.session.preparations import throw_aborted
from dsh.session.query_engine import SqliteSessionQueryEngine, invalid_config, row_header, header_dict
from dsh.session.query_requests import MAX_PAGE_LIMIT, WHITESPACE
from dsh.session.session_query import SessionQueryService, SessionQueryError, filter_session_event_documents
from dsh.session.text_current import extract_session_event_text, compile_session_text_filter
from dsh.session.storage_contract import field


def assert_headers_compatible(first,second):
    keys=('id','createdAt','cwd','parentSession','isSeeded')
    if (any(field(first,key,None)!=field(second,key,None) for key in keys)
            or (field(first,'delegationDepth',None) or 0)!=(field(second,'delegationDepth',None) or 0)):
        raise SessionQueryError('session source headers conflict for session "%s"' % field(first,'id'),
                                'SESSION_QUERY_SOURCE_CONFLICT')


def header_value(value):
    if isinstance(value,SessionHeader):return value
    # Storage metadata is a DTO, not current-format admission; historical headers
    # keep their version until their event log is opened through the catalog.
    data=dict(value)
    result=SessionHeader(data['id'],version=data['version'],created_at=data['createdAt'],is_seeded=data.get('isSeeded'))
    for key,attr in [('cwd','cwd'),('parentSession','parent_session'),('origin','origin'),
                     ('delegationDepth','delegation_depth'),('agentPreset','agent_preset')]:
        if key in data:setattr(result,attr,data[key])
    result._extra={key:value for key,value in data.items() if key not in result.to_dict()}
    return result


async def list_persisted(persistence,signal):
    return [record['header'] for record in await list_persisted_records(persistence,signal)]


async def list_persisted_records(persistence,signal):
    try:
        return [dict(header=header_value(field(snapshot,'header')),
                     **({'formatStatus':field(snapshot,'formatStatus')} if field(snapshot,'formatStatus',None) is not None else {})) for snapshot in
                await persistence.list(None if signal is None else dict(signal=signal))]
    except Exception as error:
        throw_aborted(signal)
        raise SessionQueryError('session persistence listing failed: '+error_message(failure_value(error)),
                                'SESSION_QUERY_PERSISTENCE_FAILED',failure_value(error)) from error


async def read_stored(persistence,session_id,signal):
    try:
        loaded=await readColdSessionLog(persistence,session_id,signal)
        loaded['header']=header_value(loaded['header'])
        return loaded
    except Exception as error:
        throw_aborted(signal)
        failure=failure_value(error)
        corrupt=isinstance(failure,BaseException) and getattr(failure,'name',None)=='SessionPersistenceCorruptionError'
        prefix=('stored session "%s" is corrupt: ' if corrupt else 'failed to read stored session "%s": ') % session_id
        raise SessionQueryError(prefix+error_message(failure),
            'SESSION_QUERY_CORRUPT_SESSION' if corrupt else 'SESSION_QUERY_PERSISTENCE_FAILED',failure) from error


async def inspect_for_corpus(persistence,session_id,signal):
    loaded=await read_stored(persistence,session_id,signal)
    return dict(meta=loaded['header'],events=loaded['events'],inheritedEventCount=loaded['inheritedEventCount'])


class CurrentSessionCorpus(SessionCorpus):
    _list_persisted=staticmethod(list_persisted)
    _inspect_persisted=staticmethod(inspect_for_corpus)
    _assert_headers_compatible=staticmethod(assert_headers_compatible)


def analyze_events(session_id,events):
    return tracing.analyze_event_log(session_id,events,foldSurface)


def documents(session_id,events):
    return [dict(record,text=text) for record,event in zip(analyze_events(session_id,events)['records'],events)
            for text in [extract_session_event_text(event)] if text]


def positive_safe(value):
    return type(value) in (int,float) and 1<=value<=9007199254740991 and int(value)==value


class CurrentSessionQueryService(SessionQueryService):
    def __init__(self,ctx,persisted_read_concurrency=4,prepared_session_cache_size=5,read_window_max=50):
        # Reuse window admission with its original error ordering, without opening SQLite.
        super().__init__(ctx,open_at='never',read_window_max=read_window_max)
        for name,value in [('persistedReadConcurrency',persisted_read_concurrency),('preparedSessionCacheSize',prepared_session_cache_size)]:
            if not positive_safe(value):
                raise SessionQueryError('session-query: '+name+' must be a positive safe integer','SESSION_QUERY_INVALID_CONFIG')
        self._corpus=CurrentSessionCorpus(ctx,int(persisted_read_concurrency))
        self._observations=CurrentSessionObservationReader(ctx,int(prepared_session_cache_size))

    async def observeSession(self,session_id,options=None):
        return await self._observations.read(session_id,options)

    async def readSession(self,session_id):
        loaded=await self._corpus.load(session_id)
        CurrentSession.create(session_id,loaded['events'],loaded['header'],loaded['inheritedEventCount'],
                              format_version=loaded['header'].version)
        return dict(session=copy.deepcopy(loaded['header']),inheritedEventCount=loaded['inheritedEventCount'],
                    events=[snapshotSessionEvent(event,loaded['header'].version) for event in loaded['events']])

    async def listSessions(self,signal=None):
        throw_aborted(signal)
        persistence=self.ctx.get('sessionPersistence')
        persisted=[] if persistence is None else await list_persisted_records(persistence,signal)
        throw_aborted(signal)
        current_format=getattr(self.ctx.get('sessions'),'format_version',3)>=4
        records={record['header'].id:dict(record if current_format else {},header=copy.deepcopy(record['header']),live=False,persisted=True) for record in persisted}
        for session in self.ctx.get('sessions').list():
            stored=records.get(session.id)
            if stored is not None:assert_headers_compatible(session.header,stored['header'])
            records[session.id]=dict(header=copy.deepcopy(session.header),live=True,persisted=stored is not None,
                                    **(dict(formatStatus='current') if current_format else {}))
        return sorted(records.values(),key=lambda row:(-row['header'].createdAt,cmp_to_key(locale_compare)(row['header'].id)))

    async def readSurface(self,session_id,options=None):
        signal=options.get('signal') if isinstance(options,dict) else options
        loaded=await self._corpus.load(session_id,signal)
        return dict(session=loaded['header'],inheritedEventCount=loaded['inheritedEventCount'],capturedThroughSeq=loaded['events'][-1]['seq'] if loaded['events'] else None,
                    events=tracing.current_surface_events(session_id,loaded['events'],analyze_events,
                        lambda event:snapshotSessionEvent(event,loaded['header'].version)))

    async def listEvents(self,session_id):
        loaded=await self._corpus.load(session_id)
        return analyze_events(session_id,loaded['events'])['records']

    def filterEvents(self,session_id,filters):
        from dsh.session.session_query import _materialized_read, materialize_session_event_result_filters
        async def read(owned):
            loaded=await self._corpus.load(session_id)
            compile_text=compile_session_text_filter if getattr(self.ctx.get('sessions'),'format_version',3)>=4 else None
            return filter_session_event_documents(documents(session_id,loaded['events']),owned,compile_text=compile_text)
        return _materialized_read(filters,materialize_session_event_result_filters,read)

    async def traceEvent(self,request,signal=None):
        loaded=await self._corpus.load(request['sessionId'],signal)
        throw_aborted(signal)
        return dict(session=loaded['header'],**tracing.trace_event(request['sessionId'],loaded['events'],request['seq'],analyze_events))

    async def readEvent(self,request,signal=None):
        windows=[]
        for name in ('before','after'):
            value=request.get(name,0)
            if type(value) not in (int,float) or not 0<=value<=self._read_window_max or int(value)!=value:
                raise SessionQueryError(name+' must be an integer between 0 and '+str(self._read_window_max),'SESSION_QUERY_INVALID_WINDOW')
            windows.append(int(value))
        loaded=await self._corpus.load(request['sessionId'],signal)
        throw_aborted(signal)
        target=snapshotSessionEvent(tracing.event_target(request['sessionId'],loaded['events'],request['seq']),loaded['header'].version)
        seq=int(request['seq']);start=max(0,seq-windows[0]);end=min(len(loaded['events'])-1,seq+windows[1])
        return dict(session=loaded['header'],inheritedEventCount=loaded['inheritedEventCount'],target=target,
            events=[target if event['seq']==seq else snapshotSessionEvent(event,loaded['header'].version) for event in loaded['events'][start:end+1]],
            startSeq=start,endSeq=end)


def resolve_config(config):
    import re
    defaults=dict(openAt='startup',journalMode='wal',defaultLimit=20,maxLimit=100,snippetChars=240,
                  readWindowMax=50,persistedReadConcurrency=4,preparedSessionCacheSize=5)
    resolved=dict(path=config.get('path'))
    resolved.update({name:config.get(name) if config.get(name) is not None else default for name,default in defaults.items()})
    if not isinstance(resolved['path'],str) or not re.sub('^'+WHITESPACE+'+|'+WHITESPACE+'+$','',resolved['path']):
        raise invalid_config('path must not be blank')
    if resolved['openAt'] not in ('startup','first-search','never'):raise invalid_config('openAt is not supported')
    def integer(value):return type(value) in (int,float) and math.isfinite(value) and int(value)==value
    for name in ('defaultLimit','maxLimit'):
        if not integer(resolved[name]) or not 1<=resolved[name]<=MAX_PAGE_LIMIT:
            raise invalid_config(name+' must be an integer between 1 and '+str(MAX_PAGE_LIMIT))
    if not integer(resolved['snippetChars']) or resolved['snippetChars']<1:raise invalid_config('snippetChars must be a positive integer')
    if not integer(resolved['readWindowMax']) or resolved['readWindowMax']<0:raise invalid_config('readWindowMax must be a non-negative integer')
    for name in ('persistedReadConcurrency','preparedSessionCacheSize'):
        if not positive_safe(resolved[name]):raise invalid_config(name+' must be a positive safe integer')
    if resolved['defaultLimit']>resolved['maxLimit']:raise invalid_config('defaultLimit must be less than or equal to maxLimit')
    if resolved['journalMode'] not in ('wal','delete','truncate','persist'):raise invalid_config('journalMode is not supported')
    return resolved


def same_snapshots(first,second):
    if first.keys()!=second.keys():return False
    for session_id,before in first.items():
        after=second[session_id]
        if before['revision']!=after['revision']:return False
        try:assert_headers_compatible(before['header'],after['header'])
        except SessionQueryError:return False
        if field(before['header'],'agentPreset',None)!=field(after['header'],'agentPreset',None):return False
    return True


def observe(header,events,inherited_event_count=0):
    # The fingerprint uses the exact same detached header/events/cut. v3's surface
    # classifier must run before the old event vocabulary can reject system heads.
    from dsh.cordis.json_text import stringify_json
    import base64,hashlib
    detached_header,detached_events=copy.deepcopy(header),copy.deepcopy(list(events))
    fingerprint=base64.urlsafe_b64encode(hashlib.sha256(stringify_json(dict(header=header_dict(detached_header),
        inheritedEventCount=inherited_event_count,events=detached_events)).encode('utf8')).digest()).decode('ascii').rstrip('=')
    return dict(header=detached_header,inheritedEventCount=inherited_event_count,
                documents=documents(field(header,'id'),detached_events),fingerprint=fingerprint)


class CurrentSqliteSessionQueryEngine(SqliteSessionQueryEngine,CurrentSessionQueryService):
    _resolve_config=staticmethod(resolve_config)
    _assert_headers_compatible=staticmethod(assert_headers_compatible)
    _same_snapshots=staticmethod(same_snapshots)
    _observe=staticmethod(observe)

    def _initialize_query(self,ctx,resolved):
        CurrentSessionQueryService.__init__(self,ctx,resolved['persistedReadConcurrency'],
            resolved['preparedSessionCacheSize'],resolved['readWindowMax'])

    async def _read_snapshots(self,persistence,signal):
        return await persistence.list(None if signal is None else dict(signal=signal))

    async def _read_stored(self,persistence,session_id,signal):
        return await readColdSessionLog(persistence,session_id,signal)

    def _row_header(self,row):
        header=row_header(row)
        header.version=getattr(self.ctx.get('sessions'),'format_version',3)
        return header


class CurrentSqliteSessionQueryPlugin(Plugin):
    id='session-query-sqlite'
    name='@deepseek-ai/dsh-session-query-sqlite'
    inject=['sessions']

    async def apply(self,ctx):
        config=dict(self.config)
        config.setdefault('path',':memory:')
        query=CurrentSqliteSessionQueryEngine(ctx,config)
        ctx.set_service('sessionQuery',query)
        await query.initialize()
