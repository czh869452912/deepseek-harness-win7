"""Detachable Win7 pipe reader; never closes the launcher's stdin handle."""
import asyncio
import os
import select


class StdioInput:
    def __init__(self, stream):
        self.stream = stream
        self.listeners = {}
        self.readableEnded = False
        self.task = None
        self.closed = False
        self.fd = stream.fileno()
        self.peek = self.handle = None
        if os.name == 'nt':
            import ctypes
            import msvcrt
            self.handle = msvcrt.get_osfhandle(self.fd)
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.GetFileType.argtypes = [ctypes.c_void_p]
            self.kernel.GetFileType.restype = ctypes.c_ulong
            kind = self.kernel.GetFileType(self.handle)
            if kind == 3:  # Named and anonymous pipes; available on Windows 7.
                self.peek = self.kernel.PeekNamedPipe
                self.peek.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                                      ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
                self.peek.restype = ctypes.c_int
            elif kind != 1:
                raise RuntimeError('SDK stdio requires a pipe or redirected file on Windows')

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)
        if event == 'data' and self.task is None and not self.closed:
            self.task = asyncio.create_task(self.read())
        return self

    def once(self, event, callback):
        def once_callback(*args):
            self.off(event, once_callback)
            callback(*args)
        once_callback.original = callback
        return self.on(event, once_callback)

    def off(self, event, callback):
        self.listeners[event] = [item for item in self.listeners.get(event, [])
                                 if item != callback and getattr(item, 'original', None) != callback]

    def emit(self, event, *args):
        for callback in list(self.listeners.get(event, [])):
            callback(*args)

    def available(self):
        if self.peek is not None:
            import ctypes
            count = ctypes.c_ulong()
            if not self.peek(self.handle, None, 0, None, ctypes.byref(count), None):
                error = ctypes.get_last_error()
                if error in (109, 232, 233):
                    return -1
                raise ctypes.WinError(error)
            return min(count.value, 65536)
        if os.name == 'nt':
            return 65536  # Disk input cannot wait for a writer.
        readable, _, _ = select.select([self.fd], [], [], 0)
        return 65536 if readable else 0

    async def read(self):
        try:
            while not self.closed:
                available = self.available()
                if not available:
                    await asyncio.sleep(.01)
                    continue
                chunk = os.read(self.fd, available) if available > 0 else b''
                if not chunk:
                    self.readableEnded = True
                    self.emit('end')
                    return
                self.emit('data', chunk)
                await asyncio.sleep(0)
        except (OSError, ValueError) as error:
            self.emit('error', error)

    async def close(self):
        self.closed = True
        if self.task is not None and self.task is not asyncio.current_task():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.listeners.clear()
