"""Shared out-of-process backend settlement, diagnostics and disposal ownership."""
import asyncio
import inspect
import math
import os
from types import MappingProxyType,SimpleNamespace
from dsh.cordis.awaiting import start_coroutine
from dsh.core.session.json import UNDEFINED

NO_START_CAPABILITIES=MappingProxyType(dict(agentOptions=False,agentPreset=False,outputSchema=False,depthLimit=False))
SUFFIX='\n[diagnostic truncated]'


def limit_diagnostic(text):
    data=text.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace').encode('utf-8')
    if len(data)<=4096:return text
    prefix=4096-len(SUFFIX.encode('utf-8'))
    while data[prefix]&0xC0==0x80:prefix-=1
    return data[:prefix].decode('utf-8')+SUFFIX


def assert_positive_finite(prefix,name,value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
        raise RuntimeError('%s: %s must be a positive finite number' % (prefix,name))


def assert_usable_cwd(prefix,label,cwd):
    if not os.path.isabs(cwd):raise RuntimeError('%s: %s must be an absolute path: %s' % (prefix,label,cwd))
    if not os.path.isdir(cwd) or not os.access(cwd,os.X_OK):
        raise RuntimeError('%s: %s is not an accessible directory: %s' % (prefix,label,cwd))
    return cwd


def settle_run_result(parts):
    async def settle():
        try:
            result=await parts['attempt']()
            if parts['cancelled']():return dict(output=parts['collectOutput'](),stopReason='aborted')
            if 'diagnostic' in result:result=dict(result,diagnostic=limit_diagnostic(result['diagnostic']))
            return result
        except Exception as error:
            if parts['cancelled']():return dict(output=parts['collectOutput'](),stopReason='aborted')
            try:
                if parts.get('onError') is not None:parts['onError'](error,'error')
            except Exception:pass
            diagnostic=parts['collectDiagnostic']() if parts.get('collectDiagnostic') is not None else UNDEFINED
            result=dict(output=parts['collectOutput'](),stopReason='error')
            if diagnostic is not UNDEFINED:result['diagnostic']=limit_diagnostic(diagnostic)
            return result
        finally:parts['signal'].removeEventListener('abort',parts['onAbort'])
    return start_coroutine(settle())


def subprocess_run_handle(parts):
    disposal=None
    def dispose():
        nonlocal disposal
        if disposal is None:
            parts['signal'].removeEventListener('abort',parts['onAbort'])
            parts['requestCancel']()
            operation=parts['teardown']()
            disposal=start_coroutine(operation) if inspect.iscoroutine(operation) else asyncio.ensure_future(operation)
        return disposal
    return SimpleNamespace(id=parts['id'],result=parts['result'],dispose=dispose)
