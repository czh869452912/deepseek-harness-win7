"""Current queued Workspace pin/archive admission over durable Domain state."""
import asyncio
import logging

from dsh.workspace.current import CurrentWorkspaceRegistry
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
        import os
        if not os.path.isdir(canonical):raise ValueError("cannot create a workspace at '%s': path is not a directory" % canonical)
        return await self._enqueue(lambda:super(Current022WorkspaceRegistry,self).create(canonical,title))

    def delete(self,identity):
        return self._enqueue(lambda:super(Current022WorkspaceRegistry,self).delete(identity))

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
