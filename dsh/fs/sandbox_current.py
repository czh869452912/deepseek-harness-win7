"""Current filesystem fence for every mutation, including both move endpoints."""
from dsh.cordis.awaiting import start_coroutine
from dsh.core.cleanup import CleanupPromise
from dsh.sandbox.roots_current import writable_roots
from .fs_local import FsError,FsTarget
from .fs_sandbox import is_path_under
from .local_current import CurrentFileSystem,CurrentFsLocal


class CurrentSandboxedFileSystem(CurrentFileSystem):
    def __init__(self,ctx,**config):
        super().__init__(**config);self.ctx=ctx;self.default_mode=ctx.sandboxPolicy.defaultMode

    @property
    def sandboxMode(self):return self.default_mode

    @property
    def sandbox_mode(self):return self.default_mode

    async def _checked_target(self,target,policy):
        policy=self.ctx.sandboxPolicy.resolve() if policy is None else policy
        if policy['mode']=='danger-full-access':return target
        display=target.displayPath if isinstance(target,FsTarget) else self.resolve_path(target)
        if policy['mode']=='read-only':raise FsError('cannot write "'+display+'": file access denied under read-only mode','FS_SANDBOX_DENIED')
        fresh=await self.resolve(display)
        for root in writable_roots(policy):
            if await is_path_under(fresh.targetKey,root):return fresh
        raise FsError('cannot write "'+display+'": file access denied under workspace-write mode','FS_SANDBOX_DENIED')

    def _guarded(self,method,targets,args,policy):
        async def execute():
            checked=[]
            for target in targets:checked.append(await self._checked_target(target,policy))
            return await method(*checked,*args)
        return CleanupPromise(start_coroutine(execute()))

    def writeText(self,target,content,expected=None,signal=None,sandbox_policy=None):
        return self._guarded(super().writeText,[target],[content,expected,signal],sandbox_policy)

    def editText(self,target,edit,expected=None,signal=None,sandbox_policy=None):
        return self._guarded(super().editText,[target],[edit,expected,signal],sandbox_policy)

    def patchText(self,target,hunks,expected=None,signal=None,sandbox_policy=None):
        return self._guarded(super().patchText,[target],[hunks,expected,signal],sandbox_policy)

    def deleteFile(self,target,expected=None,signal=None,sandbox_policy=None):
        return self._guarded(super().deleteFile,[target],[expected,signal],sandbox_policy)

    def moveFile(self,source,destination,options,signal=None,sandbox_policy=None):
        return self._guarded(super().moveFile,[source,destination],[options,signal],sandbox_policy)


class CurrentFsSandbox(CurrentFsLocal):
    name='fs-sandbox'
    inject=['sandboxPolicy']
    def apply(self,ctx):ctx.set_service('fs',CurrentSandboxedFileSystem(ctx,cwd=self.config['cwd'],diff_basis_max_bytes=self.config['diffBasisMaxBytes']))
