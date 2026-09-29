"""Workspace business Remote and reconnect-safe committed domain feed."""
import asyncio
import copy

from dsh.api.settings import failure
from dsh.typert.remote import Remote, TypertRemoteFailure, TypertRemoteService
from dsh.workspace.workspace import WorkspaceOrderInvalidError, WorkspaceUnknownSessionError
from dsh.workspace.entity import WorkspaceMoveInvalidError
from dsh.workspace.spec import workspace_record, workspace_domain_state


class WorkspaceController(TypertRemoteService):
    inject = ['typert', 'workspaceRegistry']

    def __init__(self, ctx):
        super().__init__(ctx, 'workspaceController', {'namespace': 'workspace'})
        self._commands = asyncio.Lock()
        self._followers = set()
        self._order = [workspace.id for workspace in self._registry().list()]
        self._known, self._archived = set(self._order), self._registry().archivedSessionIds
        ctx.on('domain/changed', self._changed)
        def close():
            for follower in self._followers:
                follower.put_nowait(None)
            self._followers.clear()
        ctx.effect(lambda: close)
        from dsh.api.directory_picker import DirectoryPickerController
        ctx.plugin(DirectoryPickerController)

    def _registry(self):
        return self.ctx.get('workspaceRegistry')

    def _require(self, identity):
        value = self._registry().get(identity)
        if value is None:
            raise failure('workspace-not-found', 'Workspace "%s" not found' % identity, {'workspaceId': identity})
        return value

    @Remote
    async def create(self, request):
        async with self._commands:
            try:
                existing = await self._registry().resolveByPath(request['path'])
                workspace = existing if existing is not None else await self._registry().create(request['path'])
                return dict(workspace=workspace.to_dict(), created=existing is None)
            except TypertRemoteFailure:
                raise
            except Exception as error:
                raise failure('workspace-invalid-path', 'cannot create a Workspace at "%s": %s' % (request['path'], error), {'path': request['path']}) from error

    @Remote
    async def rename(self, request):
        title = request['title'].strip()
        if not title:
            raise failure('bad-request', 'Workspace rename requires a non-blank title')
        async with self._commands:
            workspace = self._require(request['workspaceId'])
            if title != workspace.title:
                if any(row.id != workspace.id and row.title == title for row in self._registry().list()):
                    raise failure('workspace-name-conflict', "Workspace name '%s' is already in use" % title, {'name': title})
                await workspace.setTitle(title)
            return {'workspace': workspace.to_dict()}

    @Remote
    async def delete(self, request):
        async with self._commands:
            if not await self._registry().delete(request['workspaceId']):
                self._require(request['workspaceId'])
            return {'deleted': True}

    @Remote
    async def insertBefore(self, request):
        try:
            return {'workspaceIds': await self._registry().insertBefore(request['workspaceId'], request.get('beforeWorkspaceId'))}
        except WorkspaceOrderInvalidError as error:
            raise failure('workspace-not-found', 'Workspace "%s" not found' % error.workspace_id, {'workspaceId': error.workspace_id}) from error

    @Remote
    async def insertSessionBefore(self, request):
        workspace = self._require(request['workspaceId'])
        try:
            await workspace.insertSessionBefore(request['sessionId'], request.get('beforeSessionId'))
        except WorkspaceMoveInvalidError as error:
            raise failure('workspace-move-invalid', str(error), dict(request)) from error
        return {'workspace': workspace.to_dict()}

    @Remote
    async def archiveSession(self, request):
        try:
            await self._registry().archiveSession(request['sessionId'])
        except WorkspaceUnknownSessionError as error:
            raise failure('session-not-found', str(error), {'sessionId': request['sessionId']}) from error
        return {'archivedSessionIds': self._registry().archivedSessionIds}

    @Remote({'mode': 'stream'})
    async def follow(self, signal):
        signal.throw_if_aborted()
        follower = asyncio.Queue()
        self._followers.add(follower)
        release = signal.add_listener('abort', lambda *_: follower.put_nowait(None))
        try:
            yield dict(type='baseline', value=dict(items=[row.to_dict() for row in self._registry().list()],
                                                  archivedSessionIds=self._registry().archivedSessionIds))
            while not signal.aborted:
                frame = await follower.get()
                if frame is None:
                    return
                yield frame
        finally:
            release()
            self._followers.discard(follower)

    def _publish(self, frame):
        for follower in self._followers:
            follower.put_nowait(copy.deepcopy(frame))

    def _changed(self, change):
        if change.domain != 'workspace':
            return
        if change.table == '':
            if change.operation != 'put':
                return
            state = workspace_domain_state.parse(change.value)
            for identity in state['workspaceIds']:
                if identity not in self._known:
                    workspace = self._require(identity)
                    self._known.add(identity)
                    self._publish(dict(type='upsert', workspace=workspace.to_dict()))
            if self._order != state['workspaceIds']:
                self._order = list(state['workspaceIds'])
                self._publish(dict(type='order', workspaceIds=self._order))
            if self._archived != state['archivedSessionIds']:
                self._archived = list(state['archivedSessionIds'])
                self._publish(dict(type='archived', archivedSessionIds=self._archived))
        elif change.table == 'workspaces':
            if change.key not in self._known:
                return
            if change.operation == 'deleted':
                self._known.remove(change.key)
                self._publish(dict(type='remove', workspaceId=change.key))
            else:
                self._publish(dict(type='upsert', workspace=dict(workspaceId=change.key, **workspace_record.parse(change.value))))
