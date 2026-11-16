"""Current baseline workspace previews, bounded search and target watches."""
import ntpath
import posixpath
import re
from urllib.parse import unquote,urlsplit

from dsh.api.workspace_files_current import CurrentWorkspaceFiles,DEFAULTS
from dsh.cordis.schema import Schema as z
from dsh.cordis.text import trim_js
from dsh.api.workspace_search import search_workspace,DEFAULTS as SEARCH_DEFAULTS
from dsh.api.workspace_changes_022 import WorkspaceChangeFeed
from dsh.typert.remote import Remote,RemoteError,TypertRemoteService
from dsh.typert.stores import field


class CurrentWorkspaceFiles022(TypertRemoteService):
    inject=['fs','sandboxPolicy','sessions','typert']
    Config=z.object(dict(
        maxBytes=z.natural().min(1).default(DEFAULTS['maxBytes']),
        maxFileBytes=z.natural().min(1).max(9007199254740990).default(DEFAULTS['maxFileBytes']),
        maxLines=z.natural().min(1).default(DEFAULTS['maxLines']),
        maxEntries=z.natural().min(1).default(DEFAULTS['maxEntries']),
        search=z.object(dict(maxResults=z.natural().min(1).default(512),maxEntries=z.natural().min(1).default(100000),
            graceMs=z.natural().min(1).max(2147483647).default(3000),timeoutMs=z.natural().min(1).max(2147483647).default(30000),
            stderrMaxBytes=z.natural().min(1).default(65536))).default({})))

    def __init__(self,ctx,config=None):
        super().__init__(ctx,'workspaceFiles')
        self.caps=dict(DEFAULTS,**(config or {}))
        self.search_caps=dict(SEARCH_DEFAULTS,**self.caps.get('search',{}))
        self.feed=WorkspaceChangeFeed(ctx)
        def lookup(scope):
            async def resolve(sid):
                session=scope.get('sessions').get(sid)
                live=session.header if session is not None else None
                persistence=scope.get('sessionPersistence')
                stored=await persistence.stat(sid) if live is None and persistence is not None else None
                header=live if live is not None else field(stored,'header') if stored is not None else None
                if header is None:return None
                cwd=field(header,'cwd')
                return dict(sessionId=sid,workspaceRoot=cwd if cwd is not None else field(scope.get('sandboxPolicy'),'workspaceRoot'))
            scope.get('typert').lookups.register('workspaceFileScope',dict(parameter='workspaceFileScope',wire='workspaceFileScopeId',resource='session',
                hostTypeSymbol='@deepseek-ai/dsh-api-workspace-files#WorkspaceFileScope',wireTypeSymbol='@deepseek-ai/dsh-session/types#SessionId',resolve=resolve))
        ctx.inject(['sessions','typert'],lookup)

    resolve_page=CurrentWorkspaceFiles.resolve_page
    resolve_window=CurrentWorkspaceFiles.resolve_window
    inspect=CurrentWorkspaceFiles.inspect
    locate_file=CurrentWorkspaceFiles.locate_file
    stat_of=CurrentWorkspaceFiles.stat_of
    read=CurrentWorkspaceFiles.read
    stat=CurrentWorkspaceFiles.stat

    @Remote(dict(mode='stream'))
    def changes(self,workspaceFileScope,path,signal):
        return self.feed.follow(field(workspaceFileScope,'workspaceRoot'),path,signal)

    async def relative_path(self,scope,base_file,path,signal):
        relative=path.replace('\\','/')
        if not relative or relative.startswith('/') or re.match(r'^[a-zA-ZſK][a-zA-ZſK0-9+.-]*:',relative) or '\0' in relative:
            raise RemoteError('gateway/bad-request','path must be relative when baseFile is provided',{})
        target,_=await self.locate_file(scope,base_file,signal)
        absolute=self.ctx.get('fs').processPath(target);paths=posixpath if absolute.startswith('/') else ntpath
        return paths.normpath(paths.join(paths.dirname(absolute),relative))

    @Remote
    async def readBytes(self,workspaceFileScope,path,options,signal):
        window=self.resolve_window(options['range'],path) if 'range' in options else None
        resolved=await self.relative_path(workspaceFileScope,options['baseFile'],path,signal) if 'baseFile' in options else path
        target,info=await self.locate_file(workspaceFileScope,resolved,signal)
        fs=self.ctx.get('fs')
        if window is not None:
            offset,length=window
            data=await fs.readByteRange(target,dict(offset=offset,length=length),signal)
            size=field(info,'size');eof=len(data)<length if size is None else offset+len(data)>=size
            return dict(self.stat_of(target,info),offset=offset,data=data,eof=eof)
        limit=self.caps['maxFileBytes']
        try:data=await fs.readBytes(target,signal,limit)
        except Exception as cause:
            if getattr(cause,'code',None)=='FS_TOO_LARGE':
                raise RemoteError('workspace-file/too-large','"{}" exceeds the {} byte full-file cap'.format(path,limit),dict(path=path,limit=limit),cause=cause) from None
            raise
        return dict(self.stat_of(target,info),offset=0,data=data,eof=True)

    async def confine(self,root,workspace_root,path,signal):
        fs=self.ctx.get('fs');target=await fs.resolve(path,dict(cwd=workspace_root,signal=signal))
        if not fs.contains(root,target):raise RemoteError('workspace-file/outside-workspace','"{}" is outside the workspace'.format(path),dict(path=path))
        return target

    @Remote
    async def list(self,workspaceFileScope,path,signal):
        root,workspace_root,entry=await self.inspect(workspaceFileScope,path,signal)
        kind=field(entry,'type')
        if kind not in ('directory','symlink'):
            raise RemoteError('workspace-file/not-directory','"{}" is a {}'.format(path,kind),dict(path=path,kind=kind))
        fs=self.ctx.get('fs');target=await self.confine(root,workspace_root,path,signal)
        if kind=='symlink':
            info=await fs.stat(target,signal)
            if field(info,'type')!='directory':raise RemoteError('workspace-file/not-directory','"{}" does not resolve to a directory'.format(path),dict(path=path,kind='symlink'))
        children=await fs.listDir(target,signal)
        root_path=urlsplit(fs.fileUrl(root)).path.rstrip('/');target_path=urlsplit(fs.fileUrl(target)).path
        workspace_path='' if target_path==root_path else '/'.join(unquote(segment,errors='strict') for segment in target_path[len(root_path)+1:].split('/'))
        entries=[]
        for child in children[:self.caps['maxEntries']]:
            value=dict(name=field(child,'name'),type=field(child,'type'))
            if field(child,'size') is not None:value['size']=field(child,'size')
            entries.append(value)
        return dict(path=workspace_path,entries=entries,truncated=len(children)>self.caps['maxEntries'])

    @Remote
    async def search(self,workspaceFileScope,request,signal):
        query=trim_js(request['query'])
        if not query:raise RemoteError('gateway/bad-request','query must not be blank',{})
        signal.throwIfAborted();workspace_root=field(workspaceFileScope,'workspaceRoot');fs=self.ctx.get('fs')
        root=await fs.resolve(workspace_root,dict(signal=signal));info=await fs.stat(root,signal)
        if info is None:raise RemoteError('workspace-file/not-found','no entry at "{}"'.format(workspace_root),dict(path=workspace_root))
        kind=field(info,'type')
        if kind!='directory':raise RemoteError('workspace-file/not-directory','"{}" is a {}'.format(workspace_root,kind),dict(path=workspace_root,kind=kind))
        subprocess=self.ctx.get('subprocess')
        if subprocess is None:raise RemoteError('workspace-file/search-failed','Workspace file search requires a subprocess provider',{})
        return await search_workspace(subprocess,dict(self.search_caps,cwd=fs.processPath(root),query=query,
            excludedPaths=request['excludedPaths'],includeHidden=request['includeHidden'],respectGitignore=request['respectGitignore']),signal)
