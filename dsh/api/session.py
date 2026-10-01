"""Canonical Session business Remote over Agent, Session and Workspace services."""
import asyncio
import base64
import os
import uuid

from dsh.api.settings import failure, settled
from dsh.api.session_agents import SessionAgents
from dsh.api.session_history import SessionHistory
from dsh.api.session_control import SessionControl
from dsh.api.session_list import SessionList
from dsh.attachment.admission import admit_encoded_images
from dsh.attachment.error import AttachmentError
from dsh.context.time_context.request_zone import browser_time_zone
from dsh.host.native_command import can_open_path, open_path
from dsh.llm.message import create_user_message
from dsh.llm.error import error_chain
from dsh.presets.preset import UnknownPresetError, PresetMountError
from dsh.typert.remote import TypertRemoteService, TypertRemoteFailure, Remote


class SessionController(TypertRemoteService):
    inject = ['agentDefaultModel', 'agents', 'attachments', 'llm', 'sessions',
              'sessionProjections', 'sessionQuery', 'typert', 'workspaceRegistry']

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'sessionController', {'namespace': 'session'})
        self.config = config or {}
        self.agents = SessionAgents(ctx)
        self.promotions = set()
        ctx.effect(lambda: self.drain)
        self.history = SessionHistory(ctx, self.promote)
        self.control_state = SessionControl(ctx)
        self.list_state = SessionList(ctx, self.config.get('coldBlankProbeMaxBytes', 1024))
        from dsh.api.session_catalogs import SessionFileReferences, SessionSkillCatalog
        ctx.plugin(SessionFileReferences)
        ctx.plugin(SessionSkillCatalog)
        ctx.on('session/created', lambda session: ctx.emit('api-session/added', self.list_state.summary_for(session)))
        ctx.on('session/disposed', lambda session: ctx.emit('api-session/removed', session.id))
        ctx.on('agent/status', lambda value: ctx.emit('api-session/status', value['agent'].id, value['status'] == 'running'))
        ctx.on('agent/error', lambda value: ctx.emit('api-session/error', value['agent'].id, error_chain(value['error'])))
        ctx.on('session/event', self.event)

    def event(self, session, event):
        if event['type'] == 'request/header':
            agent = self.ctx.get('agents').get(session.id)
            if agent is not None and agent.session is session:
                selected = self.agents.selection(agent)
                config = event['data']['header']['config']
                if selected.picked is not None and all(selected.picked.get(key) == config.get(key) for key in ('provider', 'model', 'reasoningEffort')):
                    selected.picked = None
        if event['type'] == 'user/message' and event['data']['source']['kind'] == 'user':
            self.ctx.emit('api-session/activity', session.id, event['time'])

    def promote(self, observation):
        async def activate():
            try:
                await self.agents.resolve(observation.header.id, observation)
            except Exception as error:
                self.ctx.emit('api-session/error', observation.header.id, error_chain(error))
            finally:
                observation.dispose()
        task = asyncio.create_task(activate())
        self.promotions.add(task)
        task.add_done_callback(self.promotions.discard)

    async def drain(self):
        await asyncio.gather(*list(self.promotions), return_exceptions=True)

    async def resolveAgent(self, sessionId):
        try:
            return {'agent': await self.agents.resolve(sessionId)}
        except TypertRemoteFailure as error:
            return {'error': error.failure}

    async def inspect(self, sessionId, signal=None):
        source = await self.ctx.get('sessionQuery').observeSession(sessionId, dict(signal=signal, projectionMode='none'))
        try:
            return dict(meta=source.header, events=list(source.events))
        finally:
            source.dispose()

    @Remote
    async def list(self, _request, signal):
        return dict(items=await self.list_state.list(signal))

    @Remote
    async def search(self, request, signal):
        query = request['query'].strip()
        if not query or len(query.encode('utf-16-le', 'surrogatepass')) // 2 > 500 or '\0' in query:
            raise failure('bad-request', 'session search query must be non-empty, contain no NUL, and contain at most 500 UTF-16 code units')
        provider = self.ctx.get('sessionQuery')
        visible = {row['header'].id for row in await provider.listSessions(signal) if row['header'].cwd is not None}
        accepted, seen, cursors, cursor = [], set(), set(), None
        for _ in range(100):
            signal.throw_if_aborted()
            payload = dict(query=query, limit=20, eventFilters=[dict(kind='type', values=['user/message', 'assistant/message']), dict(kind='surface', values=['current'])])
            if cursor is not None:
                payload['cursor'] = cursor
            try:
                page = await provider.searchSessions(payload, dict(signal=signal))
            except Exception as error:
                if getattr(error, 'code', None) == 'SESSION_QUERY_STALE_CURSOR':
                    accepted, seen, cursors, cursor = [], set(), set(), None
                    continue
                raise failure('cancelled' if signal.aborted else 'internal', 'session search failed: ' + str(error)) from error
            if len(page['items']) > 20:
                raise failure('internal', 'session search provider exceeded its page limit')
            for hit in page['items']:
                sid, match = hit['header'].id, hit['bestMatch']
                if sid in visible and sid not in seen and match['sessionId'] == sid and match['surface'] == 'current' and match['type'] in ('user/message', 'assistant/message'):
                    seen.add(sid)
                    accepted.append(dict(sessionId=sid, snippet=match['snippet'][:240]))
            next_cursor = page.get('nextCursor')
            if next_cursor is not None:
                if next_cursor in cursors:
                    raise failure('internal', 'session search provider repeated a continuation cursor')
                cursors.add(next_cursor)
            if len(accepted) > 20 or next_cursor is None:
                return dict(items=accepted[:20], hasMore=len(accepted) > 20)
            cursor = next_cursor
        raise failure('internal', 'session search provider exceeded the 100-call work budget')

    @Remote
    async def create(self, request):
        if 'workspaceId' in request and 'cwd' in request:
            raise failure('bad-request', 'session.create accepts workspaceId or cwd, not both')
        sid = request.get('sessionId', 'session-' + str(uuid.uuid4()))
        workspace = None
        if 'workspaceId' in request:
            workspace = self.ctx.get('workspaceRegistry').get(request['workspaceId'])
            if workspace is None:
                raise failure('workspace-not-found', 'workspace "%s" not found' % request['workspaceId'], {'workspaceId': request['workspaceId']})
        cwd = workspace.path if workspace is not None else request.get('cwd', os.getcwd())
        try:
            agent = await self.agents.ensure(sid, cwd, 'sessionId' in request, request.get('agentPreset'))
        except TypertRemoteFailure:
            raise
        except UnknownPresetError as error:
            raise failure('agent-preset-not-found', str(error), dict(agentPreset=error.preset_id, available=error.available)) from error
        except PresetMountError as error:
            raise failure('agent-preset-invalid', str(error), dict(agentPreset=error.preset_id, reason=error.reason)) from error
        except Exception as error:
            raise failure('internal', 'failed to create session "%s": %s' % (sid, error)) from error
        if workspace is not None:
            await self.attach(workspace, sid)
        value = dict(sessionId=sid)
        preset = self.agents.preset(agent.session)
        if preset is not None:
            value['agentPreset'] = preset
        return value

    async def attach(self, workspace, sid):
        try:
            await workspace.attachSession(sid)
        except Exception as error:
            raise failure('workspace-attach-failed', 'session "%s" was created but could not attach to workspace "%s": %s' % (sid, workspace.id, error), dict(sessionId=sid, workspaceId=workspace.id)) from error

    @Remote
    async def selectModel(self, request):
        agent = await self.agents.resolve(request['sessionId'])
        async with self.agents.admission(agent):
            try:
                config = await self.ctx.get('llm').resolveCallConfig({key: request[key] for key in ('provider', 'model', 'reasoningEffort') if key in request})
                selected = {key: config[key] for key in ('provider', 'model', 'reasoningEffort') if key in config}
                agent.session.append('model/selection', selected)
                self.agents.selection(agent).picked = selected
                try:
                    await self.ctx.get('agentDefaultModel').saveSelection(selected)
                except Exception as error:
                    self.ctx.logger.warn('Session model changed but default was not saved: ' + str(error))
                return dict(selected=selected)
            except Exception as error:
                raise failure('model-unavailable', str(error), {key: request[key] for key in ('provider', 'model')}) from error

    @Remote
    async def modelCatalog(self):
        llm = self.ctx.get('llm')
        providers = llm.listProviders()
        async def group(provider):
            try:
                entries = []
                for model in await llm.list_models(provider['id']):
                    entry = {key: model[key] for key in ('id', 'name', 'description') if key in model}
                    resolved = await llm.resolve_model_info(provider['id'], model['id'])
                    if 'reasoning' in resolved:
                        entry['reasoning'] = resolved['reasoning']
                    entries.append(entry)
                return True, dict(id=provider['id'], name=provider['name'], models=entries)
            except Exception as error:
                return False, dict(id=provider['id'], name=provider['name'], message=str(error))
        rows = await asyncio.gather(*(group(provider) for provider in providers))
        return {'default': self.ctx.get('agentDefaultModel').currentSelection(), 'routableProviders': [row['id'] for row in providers],
                'groups': [row for success, row in rows if success and row['models']], 'failures': [row for success, row in rows if not success]}

    @Remote
    def canOpenWorkspacePath(self):
        return self.config.get('nativeOpen', can_open_path())

    @Remote
    async def openWorkspacePath(self, request, signal):
        if not request['path']:
            raise failure('bad-request', 'session.openWorkspacePath requires a non-empty path')
        signal.throw_if_aborted()
        try:
            await open_path(request['path'], signal)
            return dict(opened=True)
        except Exception as error:
            raise failure('cancelled' if signal.aborted else 'internal', 'path open was aborted' if signal.aborted else 'path open failed: ' + str(error)) from error

    @Remote
    async def rename(self, request):
        agent = await self.agents.resolve(request['sessionId'])
        titles = self.ctx.get('sessionTitle')
        if titles is None:
            raise failure('internal', 'renaming is unavailable: this deployment mounts no session-title service')
        try:
            accepted = titles.rename(agent.session, request['title'])
            return dict(title=accepted['title'], seq=accepted['eventSeq'])
        except ValueError as error:
            raise failure('title-invalid', str(error), {'sessionId': request['sessionId']}) from error

    @Remote
    async def prompt(self, request, signal):
        signal.throw_if_aborted()
        source = dict(kind='user', rpcId=request['requestId'])
        if 'clientTimeZone' in request:
            try:
                source['clientTimeZone'] = browser_time_zone(dict(source=dict(source, clientTimeZone=request['clientTimeZone'])))
                if source['clientTimeZone'] is None:
                    raise ValueError('missing zone')
            except (ValueError, TypeError) as error:
                raise failure('invalid-time-zone', 'clientTimeZone must be UTC or a valid IANA Area/Location name', {'value': request['clientTimeZone']}) from error
        agent = await self.agents.resolve(request['sessionId'])
        selection = self.agents.selection(agent).current
        if not any(row['id'] == selection.provider for row in self.ctx.get('llm').listProviders()):
            raise failure('model-unavailable', 'no adapter serves provider "%s"; select a model for this session' % selection.provider,
                          dict(provider=selection.provider, model=selection.model))
        images = [part for part in request['content'] if part['type'] == 'image']
        async def admit():
            try:
                if images:
                    chosen = self.agents.selection(agent).current
                    info = await self.ctx.get('llm').resolve_model_info(chosen.provider, chosen.model)
                    if 'inputModalities' in info and 'image' not in info['inputModalities']:
                        raise failure('attachment-error', 'Model "%s" does not support image input.' % chosen.model, {'reason': 'MODEL_DOES_NOT_SUPPORT_IMAGES'})
                refs = iter(await settled(admit_encoded_images(self.ctx.get('attachments'), images))) if images else iter([])
                content = [dict(type='text', text=part['text']) if part['type'] == 'text' else dict(type='image', attachment=next(refs)) for part in request['content']]
                message = create_user_message(dict(content=content, source=source))
                (agent.steer if request['mode'] == 'steer' else agent.followup)(message)
                return dict(accepted=True)
            except TypertRemoteFailure:
                raise
            except AttachmentError as error:
                raise failure('attachment-error', str(error), {'reason': error.code}) from error
            except Exception as error:
                raise failure('agent-busy', 'prompt rejected', {'reason': str(error)}) from error
        if images:
            async with self.agents.admission(agent):
                return await admit()
        return await admit()

    @Remote
    def cancel(self, request):
        agent = self.ctx.get('agents').get(request['sessionId'])
        if agent is None:
            raise failure('session-not-found', 'session "%s" not found (not attached)' % request['sessionId'], {'sessionId': request['sessionId']})
        self.agents.check_owner(agent.session.header, agent)
        agent.cancel({'kind': 'user'}, keep_inbox=True)
        return dict(accepted=True)

    @Remote
    def updateQueue(self, request):
        action, item_id = request['action'], request['itemId']
        if action['kind'] == 'edit' and any(part['type'] != 'text' for part in action['content']):
            raise failure('attachment-error', 'queue edits accept text content only', {'reason': 'QUEUE_EDIT_NON_TEXT'})
        agent = self.ctx.get('agents').get(request['sessionId'])
        if agent is not None:
            self.agents.check_owner(agent.session.header, agent)
        located = next(((target, message) for target, messages in [('next-turn', agent.inbox.next_turn), ('next-step', agent.inbox.next_step)] for message in messages if message['id'] == item_id), None) if agent is not None else None
        if located is None:
            raise failure('queue-item-not-found', 'queued item is no longer pending', {'itemId': item_id})
        target, message = located
        if action['kind'] == 'steer' and (target != 'next-turn' or agent.status != 'running'):
            raise failure('steer-unavailable', 'current turn no longer accepts steering', {'itemId': item_id})
        if action['kind'] == 'edit':
            agent.inbox.replace(item_id, dict(message, content=action['content']))
        else:
            agent.inbox.remove(item_id)
            if action['kind'] == 'steer':
                agent.steer(message)
        return dict(accepted=True)

    @Remote
    async def page(self, request, signal):
        return await self.history.page(request, signal)

    @Remote
    async def fork(self, request):
        anchor = request.get('atSeq')
        if anchor is not None and (type(anchor) is not int or anchor < 0):
            raise failure('bad-request', 'atSeq must be a non-negative integer')
        source = await self.ctx.get('sessionQuery').observeSession(request['sessionId'])
        try:
            boundaries = [event for event in source.events if event['type'] == 'turn/end']
            boundary = next((event for event in boundaries if event['seq'] >= anchor), None) if anchor is not None else None
            if boundary is None and (anchor is None or anchor > source.cursor):
                boundary = boundaries[-1] if boundaries else None
            if boundary is None:
                raise failure('fork-unavailable', 'session has no completed turn at the requested boundary', {'sessionId': request['sessionId']})
            cut = boundary['seq'] + 1
            while cut < len(source.events) and source.events[cut]['type'] != 'turn/start':
                cut += 1
            workspaces = self.ctx.get('workspaceRegistry').list()
            workspace = next((row for row in workspaces if source.header.id in row.sessionIds), None)
            if workspace is None and source.header.origin == 'subagent':
                headers = {row['header'].id: row['header'] for row in await self.ctx.get('sessionQuery').listSessions()}
                header, seen = source.header, set()
                while header.parentSession is not None and header.parentSession not in seen:
                    seen.add(header.parentSession)
                    workspace = next((row for row in workspaces if header.parentSession in row.sessionIds), None)
                    if workspace is not None or header.parentSession not in headers:
                        break
                    header = headers[header.parentSession]
            preset, setup = await self.agents.compose(source.projections['values'].get('agentPreset'))
            sid = 'session-' + str(uuid.uuid4())
            meta = dict(parentSession=source.header.id, seedLength=cut)
            if source.header.cwd is not None:
                meta['cwd'] = source.header.cwd
            if preset is not None:
                meta['agentPreset'] = preset
            await self.ctx.get('agents').create(dict(sessionId=sid, seed=list(source.events[:cut]), meta=meta,
                                                    agentOptions=self.agents.options(), setup=setup))
            if workspace is not None:
                await self.attach(workspace, sid)
            return dict(sessionId=sid)
        finally:
            source.dispose()

    @Remote
    async def attachment(self, request):
        source = await self.inspect(request['sessionId'])
        def find(content):
            for block in content if isinstance(content, (list, tuple)) else []:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'image' and isinstance(block.get('attachment'), dict) and block['attachment'].get('attachmentId') == request['attachmentId']:
                    return block['attachment']
                if block.get('type') == 'tool-result':
                    found = find(block.get('content'))
                    if found is not None:
                        return found
            return None
        ref = None
        for event in source['events']:
            data = event['data']
            candidates = [data.get('content'), data.get('message', {}).get('content')]
            candidates += [item.get('content') for item in data.get('inserted', [])]
            if event['type'] == 'assistant/chunk' and data.get('chunk', {}).get('type') == 'block-end':
                candidates.append([data['chunk'].get('block')])
            ref = next((found for content in candidates for found in [find(content)] if found is not None), None)
            if ref is not None:
                break
        if ref is None:
            raise failure('attachment-error', 'Image is not referenced by this session.', {'reason': 'ATTACHMENT_NOT_REFERENCED'})
        try:
            stored = await settled(self.ctx.get('attachments').read_image(ref))
            return dict(attachment=stored['ref'], data=base64.b64encode(stored['data']).decode('ascii'))
        except AttachmentError as error:
            raise failure('attachment-error', str(error), {'reason': error.code}) from error

    @Remote({'mode': 'stream'})
    def follow(self, request, signal):
        return self.history.follow(request, signal)

    @Remote({'mode': 'stream'})
    def control(self, signal):
        return self.control_state.control(signal)
