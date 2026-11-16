"""Bounded session-owned files with retained failed deletions and startup expiry."""
import asyncio
import hashlib
import os
import re
import shutil
import stat
import time
import uuid
from types import SimpleNamespace

from dsh.cordis.awaiting import start_coroutine,await_callback_result
from dsh.core.cleanup import CleanupPromise
from .errors import OfficeKitError

OWNER_DIRECTORY=re.compile(r'^session-[0-9a-f]{24}$')
OUTPUT_DIRECTORY=re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')


def _native(path):
    if os.name!='nt':return path
    from dsh.fs.fs_local import _native_path
    return _native_path(path)


def owner_directory(owner):
    text=owner.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace').encode('utf-8')
    return 'session-'+hashlib.sha256(text).hexdigest()[:24]


def _private_directories(path):
    missing=[];current=path
    while not os.path.exists(current):
        missing.append(current);parent=os.path.dirname(current)
        if parent==current:break
        current=parent
    for entry in reversed(missing):
        try:os.mkdir(entry,0o700)
        except FileExistsError:
            if not os.path.isdir(entry):raise


def _remove_tree(path):
    path=_native(path)
    try:info=os.lstat(path)
    except FileNotFoundError:return
    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
        if stat.S_ISDIR(info.st_mode):os.rmdir(path)
        else:os.unlink(path)
    elif stat.S_ISDIR(info.st_mode):shutil.rmtree(path)
    else:os.unlink(path)


def _write_output(directory,path,data):
    directory=_native(directory);path=_native(path)
    try:
        _private_directories(directory)
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0),0o600)
        try:
            with os.fdopen(descriptor,'wb') as stream:descriptor=None;stream.write(data)
        finally:
            if descriptor is not None:os.close(descriptor)
    except BaseException:_remove_tree(directory);raise


def _generated_directories(directory,pattern):
    try:
        with os.scandir(_native(directory)) as iterator:
            return [os.path.join(directory,entry.name) for entry in iterator if pattern.fullmatch(entry.name) and entry.is_dir(follow_symlinks=False)
                    and not getattr(entry.stat(follow_symlinks=False),'st_file_attributes',0)&0x400]
    except OSError:return []


async def _io(function,*args):return await asyncio.get_running_loop().run_in_executor(None,function,*args)


class OutputStore:
    def __init__(self,options,warn):
        self.options=options;self.warn=warn;self.entries={};self.bytes=0;self.disposed=False;self.pending={}
        self.sweep=CleanupPromise(start_coroutine(self.sweep_expired()))
        self.saving=asyncio.get_running_loop().create_future();self.saving.set_result(None)

    def save(self,owner,name,data):
        previous=self.saving
        async def save():
            try:await asyncio.shield(previous)
            except Exception:pass
            return await self.save_now(owner,name,data)
        saved=CleanupPromise(save())
        async def settled():
            try:await saved
            except Exception:pass
        self.saving=CleanupPromise(settled());return saved

    async def save_now(self,owner,name,data):
        await self.sweep
        if self.disposed:raise OfficeKitError('unavailable','The document converter is unavailable.')
        limit=self.options['maxBytes']
        if len(data)>limit:raise OfficeKitError('output-too-large','The output exceeds the {}-byte output store limit.'.format(limit))
        for entry in tuple(self.entries.values()):
            if self.bytes+len(data)<=limit:break
            await self.remove(entry)
        if self.bytes+len(data)>limit:raise OfficeKitError('unavailable','Earlier outputs could not be deleted to make room for this output.')
        directory=os.path.join(self.options['root'],owner_directory(owner),str(uuid.uuid4()))
        name=os.path.basename(name.rstrip('/\\') if os.name=='nt' else name.rstrip('/'));path=os.path.join(directory,name)
        try:await _io(_write_output,directory,path,data)
        except FileNotFoundError:await _io(_write_output,directory,path,data)
        entry=SimpleNamespace(path=path,directory=directory,owner=owner,bytes=len(data),removal=None,timer=None)
        entry.timer=asyncio.get_running_loop().call_later(self.options['retentionMs']/1000,lambda:self.remove(entry))
        self.entries[path]=entry;self.bytes+=len(data);return path

    def track(self,operation):
        owned=CleanupPromise(start_coroutine(operation));self.pending[owned]=None
        owned.add_done_callback(lambda done:self.pending.pop(done,None));return owned

    def release(self,owner):
        async def release():
            await asyncio.gather(*(self.remove(entry) for entry in tuple(self.entries.values()) if entry.owner==owner))
            await self.remove_empty(os.path.join(self.options['root'],owner_directory(owner)))
        return self.track(release())

    def dispose(self):
        async def dispose():
            self.disposed=True;await self.sweep;await self.saving;await self.settle()
            owners=dict.fromkeys(entry.owner for entry in self.entries.values())
            await asyncio.gather(*(self.release(owner) for owner in owners));await self.settle()
        return CleanupPromise(start_coroutine(dispose()))

    async def settle(self):
        while self.pending:await asyncio.gather(*tuple(self.pending))

    def remove(self,entry):
        if entry.removal is not None:return entry.removal
        if self.entries.get(entry.path) is not entry:
            async def removed():return True
            return CleanupPromise(removed())
        async def remove():
            entry.timer.cancel()
            try:
                try:await await_callback_result(_io(_remove_tree,entry.directory))
                except Exception as error:
                    self.warn('office-kit: could not delete output {}: {}'.format(entry.path,str(error)));return False
                self.entries.pop(entry.path);self.bytes-=entry.bytes;return True
            finally:entry.removal=None
        entry.removal=self.track(remove());return entry.removal

    @staticmethod
    async def remove_empty(directory):
        try:await _io(os.rmdir,_native(directory))
        except OSError:pass

    async def sweep_expired(self):
        cutoff=int(time.time()*1000)-self.options['retentionMs']
        for owner in await _io(_generated_directories,self.options['root'],OWNER_DIRECTORY):
            for directory in await _io(_generated_directories,owner,OUTPUT_DIRECTORY):
                try:
                    info=await _io(os.lstat,_native(directory))
                    if info.st_mtime*1000<cutoff:await _io(_remove_tree,directory)
                except Exception as error:self.warn('office-kit: could not sweep output {}: {}'.format(directory,str(error)))
            await self.remove_empty(owner)
