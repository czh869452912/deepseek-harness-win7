"""Win7 ordinary process: suspend, assign a non-breakaway Job, then resume."""
import ctypes as c
import os
import subprocess


class Accounting(c.Structure):
    _fields_=[('user',c.c_longlong),('kernel',c.c_longlong),('periodUser',c.c_longlong),
              ('periodKernel',c.c_longlong),('faults',c.c_ulong),('total',c.c_ulong),
              ('active',c.c_ulong),('terminated',c.c_ulong)]


class WindowsJobProcess:
    """Popen-shaped private plumbing with a stable Job-owned process range."""
    def __init__(self,argv, *, allow_breakaway=False, **options):
        import _winapi
        import msvcrt
        from dsh.sandbox.windows_acl import WinApi,JobLimit,P,D
        self.api=WinApi();self.job=self.process=None;self.pid=-1;self.returncode=None
        self._termination_handles={}
        self.stdin=self.stdout=self.stderr=None
        query=self.api.kernel.QueryInformationJobObject
        query.argtypes=[P,c.c_int,P,D,P];query.restype=c.c_int
        self.query=query
        child_files=[];parent_files=[];inherited=[];thread=None
        try:
            self.job=self.api.check(self.api.CreateJobObjectW(None,None),'CreateJobObjectW')
            limit=JobLimit();limit.basic.flags=0x2000 | (0x800 if allow_breakaway else 0)
            self.api.check(self.api.SetInformationJobObject(self.job,9,c.byref(limit),c.sizeof(limit)),'SetInformationJobObject')
            startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESTDHANDLES
            for name,selector,mode in [('stdin',-10,'rb'),('stdout',-11,'wb'),('stderr',-12,'wb')]:
                setting=options[name]
                if setting==subprocess.PIPE:
                    read_fd,write_fd=os.pipe()
                    parent_fd,child_fd=(write_fd,read_fd) if name=='stdin' else (read_fd,write_fd)
                    stream=os.fdopen(parent_fd,'wb' if name=='stdin' else 'rb')
                    setattr(self,name,stream);parent_files.append(stream)
                    child=os.fdopen(child_fd,mode);child_files.append(child)
                    handle=msvcrt.get_osfhandle(child.fileno())
                    os.set_handle_inheritable(handle,True)
                elif setting==subprocess.DEVNULL:
                    child=open(os.devnull,mode);child_files.append(child)
                    handle=msvcrt.get_osfhandle(child.fileno());os.set_handle_inheritable(handle,True)
                else:
                    standard=_winapi.GetStdHandle(selector)
                    if not standard or standard==-1:
                        child=open(os.devnull,mode);child_files.append(child)
                        handle=msvcrt.get_osfhandle(child.fileno());os.set_handle_inheritable(handle,True)
                    else:
                        current=_winapi.GetCurrentProcess()
                        handle=_winapi.DuplicateHandle(current,standard,current,0,True,2);inherited.append(handle)
                setattr(startup,{'stdin':'hStdInput','stdout':'hStdOutput','stderr':'hStdError'}[name],handle)
            handles=[startup.hStdInput,startup.hStdOutput,startup.hStdError]
            startup.lpAttributeList={'handle_list':list(set(handles))}
            command=subprocess.list2cmdline(argv)
            self.process,thread,self.pid,_=_winapi.CreateProcess(None,command,None,None,True,
                4|0x08000000|0x400,options.get('env'),options.get('cwd'),startup)
            self.api.check(self.api.AssignProcessToJobObject(self.job,self.process),'AssignProcessToJobObject')
            if self.api.ResumeThread(thread)==0xffffffff:raise c.WinError(c.get_last_error())
        except BaseException:
            if self.process is not None:
                self.api.TerminateProcess(self.process,1)
                self.api.WaitForSingleObject(self.process,5000)
            for stream in parent_files:stream.close()
            self.close_handles()
            raise
        finally:
            if thread is not None:_winapi.CloseHandle(thread)
            for stream in child_files:stream.close()
            for handle in inherited:_winapi.CloseHandle(handle)

    def poll(self):
        if self.returncode is not None:return self.returncode
        if self.api.WaitForSingleObject(self.process,0)==0:
            from ctypes import wintypes
            code=wintypes.DWORD()
            self.api.check(self.api.GetExitCodeProcess(self.process,c.byref(code)),'GetExitCodeProcess')
            self.returncode=code.value
        return self.returncode

    def wait(self):
        result=self.api.WaitForSingleObject(self.process,0xffffffff)
        if result!=0:raise c.WinError(c.get_last_error())
        return self.poll()

    def range_alive(self):
        if self.job is None:return False
        values=Accounting()
        self.api.check(self.query(self.job,1,c.byref(values),c.sizeof(values),None),'QueryInformationJobObject')
        if values.active:return True
        # Accounting removal can precede a member process becoming signaled.
        # Cancellation must join the actual processes, including venv launchers'
        # children, before publishing that the owned range has exited.
        for handle in self._termination_handles.values():
            state=self.api.WaitForSingleObject(handle,0)
            if state==0x102:return True
            if state!=0:self.api.error('WaitForSingleObject',c.get_last_error())
        return False

    def _retain_termination_members(self):
        capacity=16
        while True:
            class ProcessIds(c.Structure):
                _fields_=[('assigned',c.c_ulong),('listed',c.c_ulong),('ids',c.c_size_t*capacity)]
            values=ProcessIds()
            success=self.query(self.job,3,c.byref(values),c.sizeof(values),None)
            if not success and c.get_last_error()!=234:
                self.api.error('QueryInformationJobObject',c.get_last_error())
            if success and values.assigned<=capacity and values.listed==values.assigned:break
            capacity=max(capacity*2,values.assigned)
        open_process=self.api.kernel.OpenProcess
        open_process.argtypes=[c.c_ulong,c.c_int,c.c_ulong];open_process.restype=c.c_void_p
        for pid in values.ids[:values.listed]:
            if pid in self._termination_handles:continue
            handle=open_process(0x100000|0x1000,False,pid)
            if not handle:
                error=c.get_last_error()
                if error==87:continue  # The member finished before OpenProcess.
                self.api.error('OpenProcess',error)
            try:
                belongs=c.c_int()
                self.api.check(self.api.IsProcessInJob(handle,self.job,c.byref(belongs)),'IsProcessInJob')
                if belongs.value:self._termination_handles[pid]=handle;handle=None
            finally:
                if handle is not None:self.api.CloseHandle(handle)

    def kill_range(self):
        if self.job is None:return
        self._retain_termination_members()
        terminate=self.api.kernel.TerminateJobObject
        terminate.argtypes=[c.c_void_p,c.c_ulong];terminate.restype=c.c_int
        self.api.check(terminate(self.job,1),'TerminateJobObject')

    def close_handles(self):
        for handle in self._termination_handles.values():self.api.CloseHandle(handle)
        self._termination_handles.clear()
        if self.job is not None:self.api.CloseHandle(self.job);self.job=None
        if self.process is not None:self.api.CloseHandle(self.process);self.process=None
