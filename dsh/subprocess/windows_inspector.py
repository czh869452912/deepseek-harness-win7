"""Win7 Toolhelp process identities for the canonical terminal provider."""
import ctypes as c
from ctypes import wintypes as w


class ProcessEntry(c.Structure):
    _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',c.c_size_t),
        ('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),
        ('flags',w.DWORD),('exe',w.WCHAR*260)]


def process_tree(entries, root, state):
    by_pid={entry['pid']:entry for entry in entries}
    if root not in by_pid:return []
    children={}
    for entry in entries:children.setdefault(entry['parentPid'],[]).append(entry)
    visited=set();result=[]
    def visit(entry):
        pid=entry['pid']
        if pid in visited:return
        visited.add(pid)
        for child in children.get(pid,()):visit(child)
        identity=state(pid)
        if identity is not None:result.append(dict(pid=pid,started=identity['started']))
    visit(by_pid[root]);return result


class WindowsProcessInspector:
    def __init__(self):
        self.kernel=c.WinDLL('kernel32',use_last_error=True)
        definitions={
            'CreateToolhelp32Snapshot':(w.HANDLE,[w.DWORD,w.DWORD]),
            'Process32FirstW':(w.BOOL,[w.HANDLE,c.POINTER(ProcessEntry)]),
            'Process32NextW':(w.BOOL,[w.HANDLE,c.POINTER(ProcessEntry)]),
            'OpenProcess':(w.HANDLE,[w.DWORD,w.BOOL,w.DWORD]),
            'GetProcessTimes':(w.BOOL,[w.HANDLE]+[c.POINTER(w.FILETIME)]*4),
            'WaitForSingleObject':(w.DWORD,[w.HANDLE,w.DWORD]),'CloseHandle':(w.BOOL,[w.HANDLE])}
        for name,(result,args) in definitions.items():
            function=getattr(self.kernel,name);function.restype=result;function.argtypes=args

    def state(self,pid):
        handle=self.kernel.OpenProcess(0x1000|0x100000,False,pid)
        if not handle:return None
        try:
            values=[w.FILETIME() for _ in range(4)]
            if not self.kernel.GetProcessTimes(handle,*[c.byref(value) for value in values]):return None
            wait=self.kernel.WaitForSingleObject(handle,0)
            if wait not in (0,258):return None
            return dict(started=str(values[0].dwHighDateTime)+':'+str(values[0].dwLowDateTime),active=wait==258)
        finally:self.kernel.CloseHandle(handle)

    def entries(self):
        handle=self.kernel.CreateToolhelp32Snapshot(2,0)
        if handle in (None,0,c.c_void_p(-1).value):raise c.WinError(c.get_last_error())
        try:
            entry=ProcessEntry();entry.size=c.sizeof(entry);result=[]
            found=self.kernel.Process32FirstW(handle,c.byref(entry))
            while found:
                result.append(dict(pid=entry.pid,parentPid=entry.parent))
                found=self.kernel.Process32NextW(handle,c.byref(entry))
            if c.get_last_error()!=18:raise c.WinError(c.get_last_error())
            return result
        finally:self.kernel.CloseHandle(handle)

    def snapshot(self):
        owner=self
        class Snapshot:
            entries=None
            def tree(self,pid):
                if self.entries is None:self.entries=owner.entries()
                return process_tree(self.entries,pid,owner.state)
            def alive(self,identity):
                state=owner.state(identity['pid'])
                return state is not None and state['active'] and state['started']==identity['started']
        return Snapshot()
