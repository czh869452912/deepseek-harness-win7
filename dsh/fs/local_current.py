"""Current local mutation contract over the Win7 atomic filesystem backend."""
import asyncio
import os
import stat
from types import SimpleNamespace as NS

from dsh.cordis.awaiting import start_coroutine,await_callback_result
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.core.cleanup import CleanupPromise
from .fs_local import (FsService,FsError,FsEditOutcome,FsWriteOutcome,READ_CHUNK_BYTES,
    DEFAULT_DIFF_BASIS_MAX_BYTES,_throw_if_aborted,_version_of,_open_binary_read,
    _decode_utf8,_detect_line_endings,_normalize_line_endings,_restore_line_endings,_native_path)
from .patch import apply_hunks


class CurrentFileSystem(FsService):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.watchers=set()

    @staticmethod
    def _probe(path,follow=True):
        probed=FsService._probe(path,follow)
        if probed is not None and not follow and getattr(probed[0],'st_reparse_tag',0) in (0xA0000003,0xA000000C):
            # Python 3.8 reports junction mode as directory; Node lstat treats
            # the mount-point reparse tag as a symbolic link, before following.
            return probed[0],'symlink'
        return probed

    async def watch(self,target,changed,signal):
        from .watch_current import watch
        return await watch(self,target,changed,signal)

    async def _with_locks(self,keys,operation):
        ordered=sorted(set(keys),key=lambda value:value.encode('utf-16-be','surrogatepass'))
        async def acquire(index):
            if index==len(ordered):return await operation()
            return await self._locked(ordered[index],lambda:acquire(index+1))
        return await acquire(0)

    def _require_file(self,target,expected,verb):
        existing=self._probe(target.targetKey)
        if existing is None:raise FsError('cannot '+verb+' "'+target.displayPath+'": file changed since it was read','FS_STALE_VERSION')
        if existing[1]!='file':raise FsError('cannot '+verb+' "'+target.displayPath+'": not a regular file','FS_NOT_REGULAR_FILE')
        if expected is not None and _version_of(existing[0])!=expected['version']:raise FsError('cannot '+verb+' "'+target.displayPath+'": file changed since it was read','FS_STALE_VERSION')
        return existing[0]

    def _write_target(self,target,expected):
        existing=self._probe(target.targetKey)
        if existing is not None and existing[1]!='file':raise FsError('cannot write "'+target.displayPath+'": not a regular file','FS_NOT_REGULAR_FILE')
        kind=(expected or {}).get('kind')
        if kind=='replaceIfVersion':
            if existing is None:raise FsError('cannot write "'+target.displayPath+'": file no longer exists','FS_STALE_VERSION')
            if _version_of(existing[0])!=expected['version']:raise FsError('cannot write "'+target.displayPath+'": file changed since it was read','FS_STALE_VERSION')
        elif kind=='createIfAbsent' and existing is not None:raise FsError('cannot overwrite existing "'+target.displayPath+'" without reading it first','FS_NOT_OBSERVED')
        return None if existing is None else existing[0]

    async def _read_for_edit(self,target,signal):
        _throw_if_aborted(signal,'edit');chunks=[]
        try:
            with _open_binary_read(target.targetKey) as handle:
                while True:
                    _throw_if_aborted(signal,'edit');chunk=handle.read(READ_CHUNK_BYTES)
                    if not chunk:break
                    chunks.append(chunk);await asyncio.sleep(0)
        except OSError as error:
            code='FS_NOT_FOUND' if getattr(error,'errno',None) in (2,20) else 'FS_PERMISSION_DENIED' if getattr(error,'errno',None) in (1,13) else 'FS_IO_ERROR'
            raise FsError('cannot edit "'+target.displayPath+'": '+str(error),code,error)
        _throw_if_aborted(signal,'edit');raw=b''.join(chunks)
        if b'\0' in raw:raise FsError('cannot edit "'+target.displayPath+'": binary file','FS_NOT_TEXT')
        decoded=_decode_utf8(raw,'edit',target.displayPath)
        return _normalize_line_endings(decoded),_detect_line_endings(decoded)

    @staticmethod
    def _patch_content(target,before,hunks):
        result=apply_hunks(before,hunks)
        if not result['ok']:
            failure=result['failure'];raise FsError('cannot patch "'+target.displayPath+'": hunk at patch line '+str(failure['hunkLineNumber'])+' ('+failure['stage']+') does not match','FS_PATCH_MISMATCH')
        return result['after']

    def _version_after(self,target):
        after=self._probe(target.targetKey);return 'missing:'+target.targetKey if after is None else _version_of(after[0])

    async def _remove_file(self,target):
        try:
            if self.internals.removeFile is not None:await await_callback_result(self.internals.removeFile(target.targetKey))
            else:os.unlink(_native_path(target.targetKey))
        except Exception as error:
            permission=getattr(error,'code',None) in ('EACCES','EPERM') or getattr(error,'errno',None) in (1,13)
            if isinstance(error,OSError) and os.path.isdir(_native_path(target.targetKey)):permission=False
            raise FsError('cannot delete "'+target.displayPath+'": '+getattr(error,'message',str(error)),'FS_PERMISSION_DENIED' if permission else 'FS_IO_ERROR',error)

    async def _inspect_mutation(self,target):
        if self.internals.inspectBeforeMutation is not None:await await_callback_result(self.internals.inspectBeforeMutation(target))

    def patchText(self,target,hunks,expected=None,signal=None,sandbox_policy=None):
        target=self._target(target)
        async def operation():
            existing=self._require_file(target,expected,'patch');before,endings=await self._read_for_edit(target,signal);after=self._patch_content(target,before,hunks)
            await self._atomic_write(target,_restore_line_endings(after,endings),stat.S_IMODE(existing.st_mode),signal,False)
            return FsEditOutcome(self._version_after(target),before,after)
        return CleanupPromise(start_coroutine(self._locked(target.targetKey,operation)))

    def deleteFile(self,target,expected=None,signal=None,sandbox_policy=None):
        target=self._target(target)
        async def operation():
            self._require_file(target,expected,'delete');before=await self._diff_basis(target.targetKey,signal)
            await self._inspect_mutation(target);_throw_if_aborted(signal,'delete');await self._remove_file(target)
            return NS(before=before)
        return CleanupPromise(start_coroutine(self._locked(target.targetKey,operation)))

    def moveFile(self,source,destination,options,signal=None,sandbox_policy=None):
        source=self._target(source);destination=self._target(destination)
        async def operation():
            info=self._require_file(source,options.get('expectedSource'),'move');existing=self._write_target(destination,options.get('expectedDestination'))
            original,endings=await self._read_for_edit(source,signal)
            after=original if 'hunks' not in options else self._patch_content(source,original,options['hunks']);content=_restore_line_endings(after,endings)
            before=await self._diff_basis(destination.targetKey,signal) if existing is not None and len(content.encode('utf-8'))<self.diff_basis_max_bytes else None
            await self._inspect_mutation(source);_throw_if_aborted(signal,'move')
            await self._atomic_write(destination,content,stat.S_IMODE(info.st_mode),None,(options.get('expectedDestination') or {}).get('kind')=='createIfAbsent',existing_destination=existing is not None)
            outcome=FsWriteOutcome('update' if existing is not None else 'create',self._version_after(destination),before,after)
            source_before=original if len(original.encode('utf-8'))<self.diff_basis_max_bytes else None
            try:await self._remove_file(source)
            except FsError as error:return NS(sourceBefore=source_before,destination=outcome,sourceDeleted=False,sourceFailure=dict(code=error.code,message=error.message))
            return NS(sourceBefore=source_before,destination=outcome,sourceDeleted=True)
        async def start():
            if source.targetKey==destination.targetKey:raise FsError('cannot move "'+source.displayPath+'" to itself','FS_SAME_TARGET')
            return await self._with_locks([source.targetKey,destination.targetKey],operation)
        return CleanupPromise(start_coroutine(start()))


class CurrentFsLocal(Plugin):
    name='fs-local'
    Config=Schema.object(dict(cwd=Schema.string().default(os.getcwd()),diffBasisMaxBytes=Schema.number().default(DEFAULT_DIFF_BASIS_MAX_BYTES)))
    def apply(self,ctx):ctx.set_service('fs',CurrentFileSystem(cwd=self.config['cwd'],diff_basis_max_bytes=self.config['diffBasisMaxBytes']))
