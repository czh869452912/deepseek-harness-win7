"""Current Workspace commands and resource-filtered, reconnectable Domain feed."""
import asyncio
import copy

from dsh.typert.remote import Remote, RemoteError, TypertRemoteService, remote_error_of
from dsh.workspace.workspace import WorkspaceOrderInvalidError
from dsh.workspace.registry_022 import WorkspaceUnknownSessionError, WorkspaceActiveSessionError, WorkspaceArchivedSessionPinError
from dsh.workspace.entity import WorkspaceMoveInvalidError
from dsh.workspace.spec_022 import record as workspace_record, state as workspace_domain_state
from dsh.cordis.schema import Schema
from dsh.core.abort import AbortController
from dsh.core.session.json import UNDEFINED
from dsh.api.workspace_directory_current import default_workspace_directory, validate_documents_directory


class CurrentWorkspaceController(TypertRemoteService):
    inject=['remoteAccess','typert','workspaceRegistry']
    Config=Schema.object(dict(documentsDirectory=Schema.string(),documentsLookupTimeoutMs=Schema.natural().min(1).default(10000)))

    def __init__(self,ctx,config=None):
        super().__init__(ctx,'workspaceController',dict(namespace='workspace'))
        self.config=self.Config(config or {})
        if 'documentsDirectory' in self.config:validate_documents_directory(self.config['documentsDirectory'])
        ctx.get('typert').resources.register('workspace',dict(field='workspaceId'))
        self._followers=set();registry=self._registry()
        self._order=[row.id for row in registry.list()];self._known=set(self._order)
        self._archived=registry.archivedSessionIds;self._pinned=registry.pinnedSessionIds
        self._tail=asyncio.get_running_loop().create_future();self._tail.set_result(None)
        ctx.on('domain/changed',self._changed)
        def close():
            for follower in self._followers:follower.put_nowait(None)
            self._followers.clear()
        ctx.effect(lambda:close,'workspace-controller.feed')
        from dsh.api.directory_picker import DirectoryPickerController
        ctx.plugin(DirectoryPickerController)

    def _registry(self):return self.ctx.get('workspaceRegistry')

    @Remote
    async def initializeDefault(self,signal):
        async def resolve():
            combined=AbortController();release=signal.add_listener('abort',combined.abort)
            error=TimeoutError('The operation was aborted due to timeout');error.name='TimeoutError'
            timer=asyncio.get_running_loop().call_later(self.config['documentsLookupTimeoutMs']/1000,combined.abort,error)
            try:return await default_workspace_directory(self.config.get('documentsDirectory'),combined.signal)
            finally:timer.cancel();release()
        workspace=await self._registry().initializeDefault(resolve)
        return UNDEFINED if workspace is None else dict(workspace=workspace.to_dict())

    def _require(self,identity):
        value=self._registry().get(identity)
        if value is None:raise RemoteError('workspace/not-found','Workspace "%s" not found'%identity,dict(workspaceId=identity))
        return value

    def _enqueue(self,operation):
        previous=self._tail
        async def run():await asyncio.shield(previous);return await operation()
        result=asyncio.create_task(run())
        async def contain():
            try:await asyncio.shield(result)
            except BaseException:pass
        self._tail=asyncio.create_task(contain())
        return asyncio.shield(result)

    @Remote
    def create(self,request):
        async def create():
            try:
                existing=await self._registry().resolveByPath(request['path'])
                workspace=existing if existing is not None else await self._registry().create(request['path'])
                return dict(workspace=workspace.to_dict(),created=existing is None)
            except Exception as error:
                if remote_error_of(error) is not None:raise
                raise RemoteError('workspace/invalid-path','cannot create a Workspace at "%s": %s'%(request['path'],error),dict(path=request['path']),cause=error) from error
        return self._enqueue(create)

    @Remote
    def rename(self,request):
        title=request['title'].strip()
        if not title:
            rejected=asyncio.get_running_loop().create_future()
            rejected.set_exception(RemoteError('gateway/bad-request','Workspace rename requires a non-blank title',{}))
            return rejected
        async def rename():
            workspace=self._require(request['workspaceId'])
            if title!=workspace.title:
                if any(row.id!=workspace.id and row.title==title for row in self._registry().list()):
                    raise RemoteError('workspace/name-conflict',"Workspace name '%s' is already in use"%title,dict(name=title))
                await workspace.setTitle(title)
            return dict(workspace=workspace.to_dict())
        return self._enqueue(rename)

    @Remote
    def delete(self,request):
        async def delete():
            if not await self._registry().delete(request['workspaceId']):self._require(request['workspaceId'])
            return dict(deleted=True)
        return self._enqueue(delete)

    @Remote
    async def insertBefore(self,request):
        try:return dict(workspaceIds=await self._registry().insertBefore(request['workspaceId'],request.get('beforeWorkspaceId')))
        except WorkspaceOrderInvalidError as error:
            raise RemoteError('workspace/not-found','Workspace "%s" not found'%error.workspace_id,dict(workspaceId=error.workspace_id)) from error

    @Remote
    async def insertSessionBefore(self,request):
        workspace=self._require(request['workspaceId'])
        try:await workspace.insertSessionBefore(request['sessionId'],request.get('beforeSessionId'))
        except WorkspaceMoveInvalidError as error:raise RemoteError('workspace/move-invalid',str(error),dict(request),cause=error) from error
        return dict(workspace=workspace.to_dict())

    @Remote
    async def archiveSession(self,request):
        try:await self._registry().archiveSession(request['sessionId'],dict(stopActivity=True) if request.get('stopActivity') is True else {})
        except WorkspaceUnknownSessionError as error:raise RemoteError('session/not-found',str(error),dict(sessionId=request['sessionId']),cause=error) from error
        except WorkspaceActiveSessionError as error:raise RemoteError('workspace/session-active',str(error),dict(sessionId=request['sessionId'],activity=error.activity),cause=error) from error
        return dict(archivedSessionIds=self._registry().archivedSessionIds)

    @Remote
    async def unarchiveSession(self,request):
        await self._registry().unarchiveSession(request['sessionId'])
        return dict(archivedSessionIds=self._registry().archivedSessionIds)

    @Remote
    async def pinSession(self,request):
        try:await self._registry().pinSession(request['sessionId'])
        except WorkspaceUnknownSessionError as error:raise RemoteError('session/not-found',str(error),dict(sessionId=request['sessionId']),cause=error) from error
        except WorkspaceArchivedSessionPinError as error:raise RemoteError('gateway/bad-request',str(error),{},cause=error) from error
        return dict(pinnedSessionIds=self._registry().pinnedSessionIds)

    @Remote
    async def unpinSession(self,request):
        await self._registry().unpinSession(request['sessionId'])
        return dict(pinnedSessionIds=self._registry().pinnedSessionIds)

    def baseline(self):
        registry=self._registry()
        return dict(items=[row.to_dict() for row in registry.list()],archivedSessionIds=registry.archivedSessionIds,pinnedSessionIds=registry.pinnedSessionIds)

    @Remote({'mode':'stream'})
    async def follow(self,signal):
        signal.throw_if_aborted();follower=asyncio.Queue();self._followers.add(follower)
        release=signal.add_listener('abort',lambda *_:follower.put_nowait(None))
        access=self.ctx.get('remoteAccess');delivered=set()
        def visible(identity):return access.allows(dict(kind='workspace',id=identity))
        def sessions(identities):return [identity for identity in identities if access.allows(dict(kind='session',id=identity))]
        def filtered(value):
            items=[row for row in value['items'] if visible(row['workspaceId'])]
            delivered.clear();delivered.update(row['workspaceId'] for row in items)
            return dict(items=[dict(row,sessionIds=sessions(row['sessionIds'])) for row in items],archivedSessionIds=sessions(value['archivedSessionIds']),pinnedSessionIds=sessions(value['pinnedSessionIds']))
        try:
            yield dict(type='baseline',value=filtered(self.baseline()))
            while not signal.aborted:
                frame=await follower.get()
                if frame is None:return
                kind=frame['type']
                if kind=='upsert':
                    row=frame['workspace'];identity=row['workspaceId']
                    if visible(identity):
                        delivered.add(identity);yield dict(type=kind,workspace=dict(row,sessionIds=sessions(row['sessionIds'])))
                    elif identity in delivered:yield dict(type='replace',value=filtered(self.baseline()))
                elif kind=='remove':
                    if frame['workspaceId'] in delivered:
                        delivered.remove(frame['workspaceId']);yield frame
                elif kind=='order':
                    if any(identity in delivered and not visible(identity) for identity in frame['workspaceIds']):yield dict(type='replace',value=filtered(self.baseline()))
                    else:yield dict(type=kind,workspaceIds=[identity for identity in frame['workspaceIds'] if visible(identity)])
                elif kind in ('archived','pinned'):
                    key=kind+'SessionIds';yield dict(type=kind,**{key:sessions(frame[key])})
        finally:release();self._followers.discard(follower)

    def _publish(self,frame):
        for follower in self._followers:follower.put_nowait(copy.deepcopy(frame))

    def _changed(self,change):
        if change.domain!='workspace':return
        if change.table=='':
            if change.operation!='put':return
            state=workspace_domain_state(change.value)
            for identity in state['workspaceIds']:
                if identity in self._known:continue
                workspace=self._registry().get(identity)
                if workspace is None:raise RuntimeError('committed Workspace registry references missing Workspace "%s"'%identity)
                self._known.add(identity);self._publish(dict(type='upsert',workspace=workspace.to_dict()))
            if self._order!=state['workspaceIds']:
                self._order=list(state['workspaceIds']);self._publish(dict(type='order',workspaceIds=list(self._order)))
            for kind in ('archived','pinned'):
                key=kind+'SessionIds';attr='_'+kind
                if getattr(self,attr)!=state[key]:
                    setattr(self,attr,list(state[key]));self._publish(dict(type=kind,**{key:list(state[key])}))
        elif change.table=='workspaces':
            if change.operation=='deleted':
                if change.key in self._known:
                    self._known.remove(change.key);self._publish(dict(type='remove',workspaceId=change.key))
            elif change.key in self._known:self._publish(dict(type='upsert',workspace=dict(workspaceId=change.key,**workspace_record(change.value))))
