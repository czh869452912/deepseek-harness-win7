"""Bounded workspace name/path discovery through the composed process owner."""
import asyncio
import re

from dsh.cordis.utils import js_to_string
from dsh.cordis.text import lower_js,trim_js
from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from dsh.typert.remote import RemoteError
from dsh.typert.stores import field
from dsh.typert.artifact import UNDEFINED
from dsh.util.ripgrep import spawn_ripgrep,read_ripgrep_lines

DEFAULTS=dict(maxResults=512,maxEntries=100000,graceMs=3000,timeoutMs=30000,stderrMaxBytes=65536)
VCS_NAMES=('.git','.svn','.hg','.bzr','.jj','.sl')


def exclusion(path):
    literal=re.sub(r'[\\*?\[\]{}!]',lambda match:'\\'+match.group(),path)
    return '--glob=!'+('/' if '/' in path else '')+literal


def search_workspace(subprocess,spec,signal):
    async def run():
        timeout=AbortController();combined=AbortController()
        detach=[source.add_listener('abort',lambda reason:combined.abort(reason)) for source in (signal,timeout.signal)]
        timer=asyncio.get_running_loop().call_later(spec['timeoutMs']/1000,lambda:timeout.abort(RemoteError('workspace-file/search-failed',
            'Workspace file search timed out; narrow the workspace or increase search.timeoutMs',{})))
        needle=lower_js(spec['query']);by_path='/' in spec['query'];entries={}
        def admit(path,kind):
            if needle in lower_js(path if by_path else path.rsplit('/',1)[-1]):entries[path]=dict(path=path,type=kind)
        try:
            combined.signal.throwIfAborted()
            try:
                argv=['--files','--sort=path','--null','--path-separator=/']
                if spec['includeHidden']:argv.append('--hidden')
                if not spec['respectGitignore']:argv.append('--no-ignore')
                argv.extend(exclusion(path) for path in list(VCS_NAMES)+spec['excludedPaths'])
                handle=await spawn_ripgrep(subprocess,dict(argv=argv,cwd=spec['cwd'],stdio=dict(stdin='ignore',stdout='pipe',stderr=dict(maxBytes=spec['stderrMaxBytes'])),graceMs=spec['graceMs'],signal=combined.signal))
                listed=0
                def consume(path):
                    nonlocal listed
                    if listed==spec['maxEntries']:return False
                    admit(path,'file');end=path.rfind('/')
                    while end!=-1:
                        admit(path[:end],'directory');end=path.rfind('/',0,end)
                    listed+=1;return True
                result=await read_ripgrep_lines(handle,'\0',consume)
                stderr=field(handle.collected,'stderr')
                excerpt=trim_js(field(stderr.readFrom(0),'text','')) if stderr is not None else ''
            except Exception as cause:
                signal.throwIfAborted();timeout.signal.throwIfAborted()
                raise RemoteError('workspace-file/search-failed','Could not launch or read workspace file search; the subprocess provider must be able to execute the packaged ripgrep binary',{},cause=cause) from None
            outcome=result['outcome'];combined.signal.throwIfAborted()
            code=field(outcome,'exitCode',UNDEFINED);exit_signal=field(outcome,'signal',UNDEFINED)
            if not result['stopped'] and (exit_signal is not None or type(code) not in (int,float) or code not in (0,1,2)):
                raise RemoteError('workspace-file/search-failed','Workspace file search exited with code {} and signal {}; check the subprocess provider{}'.format(
                    'undefined' if code is UNDEFINED else js_to_string(code),'undefined' if exit_signal is UNDEFINED else js_to_string(exit_signal),': '+excerpt if excerpt else ''),{})
            matches=sorted(entries.values(),key=lambda row:(row['path'].count('/'),row['path'].encode('utf-16-be','surrogatepass')))
            return dict(matches=matches[:spec['maxResults']],truncated=len(matches)>spec['maxResults'],incomplete=result['stopped'] or code==2)
        finally:
            timer.cancel()
            for release in detach:release()
    return CleanupPromise(run())
