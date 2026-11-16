import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.api.workspace_files_022 import CurrentWorkspaceFiles022
from dsh.api.workspace_search import DEFAULTS,search_workspace
from dsh.cordis.text import lower_js
from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from dsh.typert.remote import RemoteError
from test_rc022_workspace_preview import setup


def request(query,**extra):return dict(dict(query=query,excludedPaths=[],includeHidden=False,respectGitignore=False),**extra)


@pytest.mark.asyncio
async def test_actual_packaged_workspace_search_matching_ignore_and_caps(tmp_path):
    names=['BUTTON.md','src/deep/Button.tsx','src/button-group/a','src/button-group/b','notes.txt',
           '.hidden/button.txt','node_modules/button.js','nested/node_modules/button.js','.git/button','.svn/button','[x]/button','x/button',
           '\u1c8a.txt','\U00010400-match','\ue000-match']
    for name in names:
        file=tmp_path/name;file.parent.mkdir(exist_ok=True,parents=True);file.write_bytes(b'')
    (tmp_path/'empty-button').mkdir();(tmp_path/'.gitignore').write_text('node_modules/\n',encoding='utf-8')
    ctx=await setup(tmp_path,search=dict(maxResults=512));await ctx.plugin(AuthorizedLocalSubprocessRuntime)
    runtime=ctx.get('subprocess');original=runtime.spawn;specs=[];home=tmp_path/'private-home';home.mkdir()
    def spawn(spec):specs.append(spec);return original(dict(spec,env=dict(HOME=str(home),USERPROFILE=str(home),XDG_CONFIG_HOME=str(home))))
    runtime.spawn=spawn;signal=AbortController().signal;scope=dict(workspaceRoot=str(tmp_path))
    async def paths(query,**extra):return [row['path'] for row in (await ctx.workspaceFiles.search(scope,request(query,**extra),signal))['matches']]
    try:
        assert await paths(' \ufeffbutton\t ')==['BUTTON.md','[x]/button','node_modules/button.js','src/button-group','x/button','nested/node_modules/button.js','src/deep/Button.tsx']
        assert '.hidden/button.txt' in await paths('button',includeHidden=True)
        assert not any('.git/' in path or '.svn/' in path for path in await paths('button',includeHidden=True))
        ignored=await paths('button',respectGitignore=True)
        assert not any('node_modules' in path for path in ignored)
        assert not any('node_modules' in path for path in await paths('button',excludedPaths=['node_modules']))
        assert '[x]/button' not in await paths('button',excludedPaths=['[x]']) and 'x/button' in await paths('button',excludedPaths=['[x]'])
        assert await paths('SRC/BUTTON')==['src/button-group','src/button-group/a','src/button-group/b']
        assert await paths('\u1c89')==['\u1c8a.txt']
        assert await paths('match')==['\U00010400-match','\ue000-match']
        assert specs[0]['argv'][0].endswith('rg.exe') and specs[0]['argv'][1]=='--no-config'
        assert specs[0]['stdio']['stdout']=='pipe'
        ctx.workspaceFiles.search_caps['maxResults']=1
        result=await ctx.workspaceFiles.search(scope,request('button'),signal)
        assert len(result['matches'])==1 and result['truncated'] and not result['incomplete']
        ctx.workspaceFiles.search_caps.update(maxResults=512,maxEntries=2)
        result=await ctx.workspaceFiles.search(scope,request('button'),signal)
        assert result['incomplete'] and not result['truncated']
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_search_missing_provider_root_and_preaborted_reason_preserved(tmp_path):
    (tmp_path/'file').write_bytes(b'x');ctx=await setup(tmp_path);signal=AbortController().signal
    try:
        for root,code in [(tmp_path,'workspace-file/search-failed'),(tmp_path/'gone','workspace-file/not-found'),(tmp_path/'file','workspace-file/not-directory')]:
            with pytest.raises(RemoteError) as error:await ctx.workspaceFiles.search(dict(workspaceRoot=str(root)),request('x'),signal)
            assert error.value.code==code
        with pytest.raises(RemoteError) as error:await ctx.workspaceFiles.search(dict(workspaceRoot=str(tmp_path)),request(' \ufeff '),signal)
        assert error.value.code=='gateway/bad-request'
        controller=AbortController();failure=RuntimeError('cancel search');controller.abort(failure)
        with pytest.raises(RuntimeError) as error:await ctx.workspaceFiles.search(dict(workspaceRoot=str(tmp_path)),request('x'),controller.signal)
        assert error.value is failure
        assert (await ctx.workspaceFiles.readBytes(dict(workspaceRoot=str(tmp_path)),'file',{},signal))['data']==b'x'
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_search_timeout_waits_for_owned_process_and_detaches_signals():
    signal=AbortController().signal;state=dict(terminated=0,exited=0);closed=asyncio.Event();done=asyncio.get_running_loop().create_future()
    class Stream:
        async def __aiter__(self):
            await closed.wait()
            if False:yield b''
        def destroy(self):closed.set()
    class Handle:
        stdout=Stream();collected={}
        def terminate(self):
            state['terminated']+=1;closed.set()
            if not done.done():done.set_result(dict(exitCode=None,signal='SIGTERM'))
        async def waitForExit(self):state['exited']+=1;return True
    child=Handle();child.done=done
    def spawn(spec):spec['signal'].add_listener('abort',lambda _:child.terminate());return child
    with pytest.raises(RemoteError) as error:
        await asyncio.wait_for(search_workspace(SimpleNamespace(spawn=spawn),dict(DEFAULTS,cwd='/',query='a',excludedPaths=[],includeHidden=False,respectGitignore=False,timeoutMs=1),signal),3)
    assert error.value.code=='workspace-file/search-failed' and 'timed out' in error.value.message
    assert state==dict(terminated=1,exited=1) and not signal._listeners


def test_search_config_defaults_and_timer_limits():
    defaults=CurrentWorkspaceFiles022.Config.validate({})['value'];assert defaults['search']==DEFAULTS
    assert CurrentWorkspaceFiles022.Config.validate(dict(search=dict(maxResults=3,timeoutMs=10)))['value']['search']==dict(DEFAULTS,maxResults=3,timeoutMs=10)
    for key in ('graceMs','timeoutMs','stderrMaxBytes'):
        for value in (0,1.5):assert CurrentWorkspaceFiles022.Config.validate(dict(search={key:value})).get('issues')
    assert CurrentWorkspaceFiles022.Config.validate(dict(search=dict(timeoutMs=2147483648))).get('issues')


@pytest.mark.parametrize('value,expected',[
    ('\u1c89','\u1c8a'),('A\u03a3','a\u03c2'),('A\u03a3B','a\u03c3b'),
    ('\u1c89\u0345\u03a3','\u1c8a\u0345\u03c2'),('A\u03a3\u1c89','a\u03c3\u1c8a'),('\U00010400','\U00010428')])
def test_unicode16_casing_keeps_new_cased_context_and_astral_letters(value,expected):
    assert lower_js(value)==expected
