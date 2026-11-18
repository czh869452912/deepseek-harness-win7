"""Accounting completion alone cannot certify a terminated process range."""
import ctypes
from types import SimpleNamespace

from dsh.subprocess.windows_process import Accounting, WindowsJobProcess


def test_zero_active_count_still_joins_retained_process_handles():
    process=WindowsJobProcess.__new__(WindowsJobProcess)
    process.job=1;process.process=2;process._termination_handles={10:3,11:4}
    states={3:0,4:0x102};closed=[]
    def query(job,kind,output,size,result):
        ctypes.cast(output,ctypes.POINTER(Accounting)).contents.active=0
        return True
    process.query=query
    process.api=SimpleNamespace(check=lambda value,name:value,WaitForSingleObject=lambda handle,timeout:states[handle],CloseHandle=closed.append)
    assert process.range_alive()
    states[4]=0
    assert not process.range_alive()
    process.close_handles()
    assert closed==[3,4,1,2] and not process._termination_handles
