"""Current queued Workspace pin/archive admission over durable Domain state."""
import asyncio
import logging
import os
import uuid

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.errors import AggregateError
from dsh.workspace.current import CurrentWorkspaceRegistry, fully_qualified_workspace_path
from dsh.workspace.entity import WorkspaceEntity, now_iso
from dsh.workspace.workspace import WorkspacePlugin
from dsh.workspace.spec_022 import workspace_domain_spec


class WorkspaceUnknownSessionError(Exception):
    def __init__(self,session_id,verb):
        super().__init__("cannot %s session '%s': live sessions and session persistence hold no such session" % (verb,session_id))
        self.name=type(self).__name__;self.sessionId=session_id


class WorkspaceActiveSessionError(Exception):
    def __init__(self,session_id,activity):
        super().__init__("cannot archive session '%s': the session is active (%s)" % (session_id,', '.join(row['kind'] for row in activity)))
        self.name=type(self).__name__;self.sessionId=session_id;self.activity=activity


class WorkspaceArchivedSessionPinError(Exception):
    def __init__(self,session_id):
        super().__init__("cannot pin session '%s': the session is archived" % session_id)
        self.name=type(self).__name__;self.sessionId=session_id


class Current022WorkspaceRegistry(CurrentWorkspaceRegistry):
    domain_spec=workspace_domain_spec

    def __init__(self,ctx):
        super().__init__(ctx)
        self.operation_tail=asyncio.get_running_loop().create_future();self.operation_tail.set_result(None)

    async def _set_state(self,value):
        # The inherited journal uses None internally to clear its optional marker.
        value={key:item for key,item in value.items() if key!='pendingMutation' or item is not None}
        await super()._set_state(value)

    def _enqueue(self,operation):
        previous=self.operation_tail
        async def run():
            await asyncio.shield(previous)
            await self._recover_pending_mutation()
            return await operation()
        result=asyncio.create_task(run())
        async def contain():
            try:await asyncio.shield(result)
            except BaseException:pass
        self.operation_tail=asyncio.create_task(contain())
        return asyncio.shield(result)

    async def create(self,path,title=None):
        # Path checks occur before entering the registry queue, as in Source.
        canonical=self._normalize_path(path)
        if not os.path.isdir(canonical):raise ValueError("cannot create a workspace at '%s': path is not a directory" % canonical)
        return await self._enqueue(lambda:self._create_canonical(canonical,title))

    def delete(self,identity):
        return self._enqueue(lambda:self._delete_known(identity))

    def initializeDefault(self,resolve_directory):
        async def initialize():
            state=self._state
            if 'defaultWorkspaceId' in state:return self._entities.get(state['defaultWorkspaceId'])
            sessions=self.ctx.get('sessions')
            if sessions is None:raise RuntimeError('default Workspace initialization requires the Session store')
            if state['workspaceIds'] or state['archivedSessionIds'] or sessions.list() or await self._list_stored_headers():return None
            path=await await_callback_result(resolve_directory())
            if not fully_qualified_workspace_path(path):raise TypeError("Workspace path is not fully qualified: '%s'" % path)
            await asyncio.get_running_loop().run_in_executor(None,lambda:os.makedirs(path,exist_ok=True))
            canonical=self._normalize_path(path)
            if await self._list_stored_headers() or sessions.list():return None
            return await self._create_canonical(canonical,self._default_title(path),True)
        return self._enqueue(initialize)

    async def _create_canonical(self,canonical,title=None,first_use=False):
        for entity in self._entities.values():
            if entity.path==canonical:return entity
        identity=str(uuid.uuid4());now=now_iso();state=self._state
        record=dict(path=canonical,title=self._default_title(canonical) if title is None else title,sessionIds=[],createdAt=now,updatedAt=now)
        entity=WorkspaceEntity(self._host,identity,record);self._entities[identity]=entity
        try:await self._set_state(dict(state,pendingMutation=dict(operation='create',workspaceId=identity)))
        except BaseException:self._entities.pop(identity,None);raise
        try:await self._table.put(identity,record)
        except BaseException as error:
            self._entities.pop(identity,None)
            try:await self._set_state(state)
            except BaseException as rollback:raise AggregateError([error,rollback],"workspace '%s' record write and pending-marker rollback both failed" % identity)
            raise
        try:
            next_state=dict(state,pendingMutation=None,initialized=True,workspaceIds=[identity]+state['workspaceIds'])
            if first_use:next_state['defaultWorkspaceId']=identity
            await self._set_state(next_state)
        except BaseException as error:
            self._entities.pop(identity,None)
            try:await self._table.delete(identity)
            except BaseException as rollback:raise AggregateError([error,rollback],"workspace '%s' order write and record rollback both failed; the pending marker remains recoverable" % identity)
            try:await self._set_state(state)
            except BaseException as rollback:raise AggregateError([error,rollback],"workspace '%s' order write and pending-marker rollback both failed" % identity)
            raise
        return entity

    async def _delete_known(self,identity):
        entity=self._entities.get(identity)
        if entity is None:return False
        state=self._state;next_state=dict(state,pendingMutation=None,initialized=True,workspaceIds=[key for key in state['workspaceIds'] if key!=identity])
        await self._set_state(dict(next_state,pendingMutation=dict(operation='delete',workspaceId=identity)))
        self._entities.pop(identity)
        try:await self._table.delete(identity)
        except BaseException as error:
            self._entities[identity]=entity
            try:await self._set_state(state)
            except BaseException as rollback:
                self._entities.pop(identity,None)
                raise AggregateError([error,rollback],"workspace '%s' record deletion and registry-order rollback both failed" % identity)
            raise
        try:await self._set_state(next_state)
        except Exception as error:logging.getLogger('workspace').warning("workspace '%s' was deleted but its pending marker could not be cleared: %s",identity,error)
        return True

    def insertBefore(self,identity,before_id=None):
        return self._enqueue(lambda:super(Current022WorkspaceRegistry,self).insertBefore(identity,before_id))

    insert_before=insertBefore

    @property
    def pinnedSessionIds(self):return list(self._state['pinnedSessionIds'])

    async def _session_known(self,identity):
        sessions=self.ctx.get('sessions')
        if sessions is not None and sessions.get(identity) is not None:return True
        if identity in self._headers:return True
        await self._index_headers(await self._list_stored_headers())
        return identity in self._headers

    def pinSession(self,identity):
        async def pin():
            if identity in self.pinnedSessionIds:return
            if identity in self.archivedSessionIds:raise WorkspaceArchivedSessionPinError(identity)
            if not await self._session_known(identity):raise WorkspaceUnknownSessionError(identity,'pin')
            await self._set_state(dict(self._state,pinnedSessionIds=[identity]+self.pinnedSessionIds))
        return self._enqueue(pin)

    def unpinSession(self,identity):
        async def unpin():
            if identity in self.pinnedSessionIds:
                await self._set_state(dict(self._state,pinnedSessionIds=[item for item in self.pinnedSessionIds if item!=identity]))
        return self._enqueue(unpin)

    def archiveSession(self,identity,options=None):
        options=options or {}
        async def archive():
            if identity in self.archivedSessionIds:return
            if not await self._session_known(identity):raise WorkspaceUnknownSessionError(identity,'archive')
            if options.get('stopActivity') is not True:
                activity=await self.ctx.waterfall('workspace/session-activity',dict(sessionId=identity),lambda:[])
                if activity:raise WorkspaceActiveSessionError(identity,activity)
            await self._set_state(dict(self._state,archivedSessionIds=self.archivedSessionIds+[identity],pinnedSessionIds=[item for item in self.pinnedSessionIds if item!=identity]))
            if options.get('stopActivity') is True:
                try:await self.ctx.parallel('workspace/session-stop',dict(sessionId=identity))
                except Exception as error:logging.getLogger('workspace').warning("workspace: stopping session '%s' for archive failed: %s",identity,error)
            try:await self.ctx.parallel('workspace/session-archived',dict(sessionId=identity))
            except Exception as error:logging.getLogger('workspace').warning('Session archived, but archive follow-up admission failed: %s',error)
        return self._enqueue(archive)

    archive_session=archiveSession

    def unarchiveSession(self,identity):
        async def unarchive():
            if identity not in self.archivedSessionIds:return
            await self.ctx.parallel('workspace/session-unarchiving',dict(sessionId=identity))
            await self._set_state(dict(self._state,archivedSessionIds=[item for item in self.archivedSessionIds if item!=identity]))
        return self._enqueue(unarchive)


class Current022WorkspacePlugin(WorkspacePlugin):
    registry_class=Current022WorkspaceRegistry
