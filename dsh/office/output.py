"""Complete regular output reads, independent of provider scratch lifetime."""
import asyncio
import os
import re
import stat

from dsh.cordis.text import JS_WHITESPACE
from dsh.core.cleanup import CleanupPromise
from .errors import OfficeKitError

PNG_SIGNATURE=b'\x89PNG\r\n\x1a\n'


def invalid_file():return OfficeKitError('invalid-output','The converter output is not a regular file.')


def _stream(descriptor):
    try:return os.fdopen(descriptor,'rb',buffering=0)
    except BaseException:os.close(descriptor);raise


def _open_output(path):
    if os.name!='nt':return _stream(os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)))
    import ctypes
    import msvcrt
    from dsh.fs.win32_stat import kernel,HandleInfo
    from dsh.fs.fs_local import _native_path
    selected=kernel();handle=selected.CreateFileW(_native_path(str(path)),0x80000000,7,None,3,0x00200000|0x02000000,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        info=HandleInfo()
        if not selected.GetFileInformationByHandle(handle,ctypes.byref(info)):raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes&(0x400|0x10):raise invalid_file()
        descriptor=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY|getattr(os,'O_NOINHERIT',0))
    except BaseException:selected.CloseHandle(handle);raise
    return _stream(descriptor)


def _metadata(stream):return os.fstat(stream.fileno())


def _read_output(path,limit,signal):
    signal.throwIfAborted();entry=os.lstat(path)
    if not stat.S_ISREG(entry.st_mode) or getattr(entry,'st_reparse_tag',0) in (0xA0000003,0xA000000C):raise invalid_file()
    with _open_output(path) as stream:
        info=_metadata(stream)
        if not stat.S_ISREG(info.st_mode):raise invalid_file()
        if info.st_size>limit:raise OfficeKitError('output-too-large','The converter output exceeds its byte limit.')
        remaining=info.st_size+1;chunks=[];length=0
        while remaining:
            signal.throwIfAborted();data=stream.read(min(remaining,65536))
            if not data:break
            chunks.append(data);length+=len(data);remaining-=len(data)
        signal.throwIfAborted()
        if length>limit:raise OfficeKitError('output-too-large','The converter output exceeds its byte limit.')
        if length!=info.st_size:raise OfficeKitError('invalid-output','The converter output changed while it was read.')
        return b''.join(chunks)


def read_output(path,limit,signal):
    async def read():return await asyncio.get_running_loop().run_in_executor(None,_read_output,path,limit,signal)
    return CleanupPromise(read())


def _ascii(data):return ''.join(chr(code&127) for code in data)


async def read_pdf(path,limit,signal):
    pdf=await read_output(path,limit,signal)
    if not re.match(r'^%PDF-[0-9]\.[0-9]',_ascii(pdf[:8])) or not _ascii(pdf[-1024:]).rstrip(JS_WHITESPACE).endswith('%%EOF'):
        raise OfficeKitError('invalid-output','The converter did not produce a complete PDF.')
    return pdf


async def read_png(path,limit,signal):
    png=await read_output(path,limit,signal)
    if not png.startswith(PNG_SIGNATURE):raise OfficeKitError('invalid-output','The converter did not produce a PNG image.')
    return png
