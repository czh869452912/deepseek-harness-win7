"""Owned stdio negotiation fixture; preserves every process and packet event."""
import ctypes
import json
import os
import sys
from pathlib import Path


def alive(pid):
    if sys.platform=='win32':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False
        try:
            code=ctypes.c_ulong();return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False


def main():
    log=Path(sys.argv[1]);mode=sys.argv[2];pid=os.getpid()
    prior=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []
    starts=[row for row in prior if row['event']=='start']
    def event(name,**values):
        with log.open('a',encoding='utf-8') as stream:stream.write(json.dumps(dict(event=name,pid=pid,**values))+'\n')
    event('start',previousAlive=alive(starts[-1]['pid']) if starts else False)
    def send(identity,result=None,error=None):
        sys.stdout.write(json.dumps(dict(jsonrpc='2.0',id=identity,**({'error':error} if error is not None else {'result':result})))+'\n');sys.stdout.flush()
    try:
        for line in sys.stdin:
            packet=json.loads(line);event('packet',packet=packet);method=packet.get('method');identity=packet.get('id')
            if identity is None:continue
            if method=='server/discover':
                if mode in ('hold','timeout'):continue
                if mode=='closed':break
                if mode=='modern':send(identity,dict(supportedVersions=['2026-07-28'],capabilities=dict(tools={}),instructions='Modern literal {{model}}',_meta={'io.modelcontextprotocol/serverInfo':dict(name='peer',version='1')}))
                else:send(identity,error=dict(code=-32601,message='Method not found'))
            elif method=='initialize':send(identity,dict(protocolVersion='2025-11-25',capabilities=dict(tools={}),serverInfo=dict(name='peer',version='1'),instructions='Legacy literal {{model}}'))
            elif method=='tools/list':send(identity,dict(tools=[],**({'resultType':'complete','ttlMs':0,'cacheScope':'private'} if mode=='modern' else {})))
            else:send(identity,error=dict(code=-32601,message='Method not found'))
    finally:event('exit')


if __name__=='__main__':main()
