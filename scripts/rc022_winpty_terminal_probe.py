"""Windows terminal activity/foreground decisions against actual Source class."""
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.subprocess.windows_inspector import process_tree
    from dsh.subprocess.terminal_authorized import WindowsTerminalHandle
    import dsh.subprocess.local as local
    rows=[];calls=[];table=[];states={}
    class Inspector:
        def snapshot(self):
            return SimpleNamespace(tree=lambda pid:process_tree(table,pid,lambda pid:states.get(str(pid))),
                alive=lambda identity:states.get(str(identity['pid']),{}).get('active') is True and states[str(identity['pid'])]['started']==identity['started'])
    async def write(data):calls.append(['write',data])
    terminal=object.__new__(WindowsTerminalHandle);terminal.pid=10;terminal.inspector=Inspector();terminal.tracked=[]
    terminal.root=dict(pid=10,started='shell');terminal.quiescent=False;terminal.activity_key=None;terminal.activity_revision=0
    terminal.raw=SimpleNamespace(write=write,_write_lock=asyncio.Lock())
    def read():return copy.deepcopy(dict(tree=process_tree(table,10,lambda pid:states.get(str(pid))),activity=None))
    scenarios=[
        ('shell',[dict(pid=10,parentPid=1)],{'10':dict(started='shell',active=True)}),
        ('child',[dict(pid=10,parentPid=1),dict(pid=11,parentPid=10)],{'10':dict(started='shell',active=True),'11':dict(started='child',active=True)}),
        ('same-child',[dict(pid=10,parentPid=1),dict(pid=11,parentPid=10)],{'10':dict(started='shell',active=True),'11':dict(started='child',active=True)}),
        ('orphan',[dict(pid=11,parentPid=1)],{'11':dict(started='child',active=True)}),
        ('reused-root',[dict(pid=10,parentPid=1),dict(pid=12,parentPid=10)],{'10':dict(started='unrelated',active=True),'11':dict(started='child',active=True),'12':dict(started='unrelated-child',active=True)}),
        ('reused-child',[],{'11':dict(started='different-child',active=True)}),
        ('gone',[],{}),
    ]
    for name,table,states in scenarios:
        result=read();result.update(name=name,activity=await terminal.inspectActivity(),foreground=await terminal.inspectForeground())
        rows.append(result)
    terminal.quiescent=True;rows.append(dict(name='quiescent',activity=await terminal.inspectActivity()))
    original=local.taskkill_process_tree
    local.taskkill_process_tree=lambda pid,force:calls.append(['taskkill',pid,force])
    try:
        for signal in ('SIGINT','SIGTERM','SIGKILL','SIGHUP','SIGTSTP'):
            try:rows.append(dict(name=signal,value=await terminal.signalForeground(signal)))
            except Exception as error:rows.append(dict(name=signal,error=str(error)))
    finally:local.taskkill_process_tree=original
    rows.append(dict(name='delivery',calls=calls))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_winpty_terminal.mts','Source LocalTerminalHandle(platform win32) and WindowsProcessTree versus native canonical WinPTY seam decisions with controlled process identities. Shell/child/orphan/root reuse/child reuse, revision stability, pseudo foreground and SIGINT/TERM/refused signals compare. Actual native WinPTY/Job/xterm/controller integration is qualified separately by pytest; no real Win7 VM or x86 claim.',[Path(__file__).resolve(),ROOT/'dsh/subprocess/terminal_authorized.py',ROOT/'dsh/subprocess/windows_inspector.py',ROOT/'dsh/subprocess/local_authorized.py',ROOT/'dsh/subprocess/winpty.py'])
