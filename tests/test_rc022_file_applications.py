import asyncio
import base64
import ctypes
import json
import os
from pathlib import Path
import sys
import uuid

import pytest

from dsh.core.abort import AbortController
from dsh.host.file_applications import native_file_applications, open_native_file_application, parse_native_file_applications
from dsh.host.native_command_current import run_native_command
from scripts.rc022_file_applications_probe import observe


@pytest.mark.asyncio
async def test_paired_intents_mapping_associations_and_owned_script_cleanup(tmp_path):
    from scripts.rc022_file_applications_probe import prepare
    # Use the same explicit fixture files as the Source observer.
    prepare(tmp_path)
    rows = await observe(tmp_path / 'files'); named = {row['name']: row for row in rows}
    assert named['long-open-invocation']['smallArgv'] and named['long-open-invocation']['path'] > 32767
    for action in ('query','long-open','wsl','cancel','failure'):
        assert named[action+'-cleanup']['gone'] and named[action+'-invocation']['bom']
    assert named['wsl-invocation']['path'] == 'C:/translated.txt'
    assert [app['id'] for app in named['mac-dedupe']['value']] == ['/Apps/preferred.app','/Apps/side.app']
    assert named['mac-launch-calls']['value'][2] == ['open','-a','/Apps/old.app','/file.txt']
    assert named['linux-catalog']['value'][0]['name'] == 'Local Editor'
    assert named['linux-catalog']['value'][0]['icon'] == 'data:image/png;base64,cGl4ZWxz'
    assert [item['kind'] for item in named['desktop-trace']['value']] == ['open','reveal','explicit','catalog']
    assert named['desktop-roundtrip']['code'] == 'gateway/bad-request'
    assert named['desktop-native-error']['hasCause']
    assert named['disabled-catalog']['value'] == []
    assert named['associated-html']['value'] == [['xdg-open','/page.html'],['open','/page.html']]


@pytest.mark.parametrize('value', [{},[None],[dict(id=1)],[dict(id='a',name='A',default=1,icon=None)],[dict(id='a',name='A',default=False,icon='javascript:alert(1)')],[dict(id='',name='A',default=False,icon=None)]])
def test_native_handler_metadata_rejects_malformed_fields_and_icons(value):
    with pytest.raises(ValueError): parse_native_file_applications(value)


@pytest.mark.asyncio
async def test_mac_raw_launch_validation_keeps_collapsed_copies_and_failures():
    async def run(command, args, signal):
        return dict(stdout='[{"id":"/a","name":"A","default":false,"icon":null,"bundle":4}]',stderr='')
    with pytest.raises(ValueError): await native_file_applications('/file', AbortController().signal, dict(platform='darwin', run=run))


@pytest.mark.asyncio
async def test_actual_gateway_admits_desktop_query_and_preserves_failures(tmp_path):
    from dsh.cordis import Context
    from dsh.api.session_authorized import AuthorizedSessionController
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_core import AuthorizedGatewayCore
    from dsh.typert.remote import RemoteError
    from dsh.api.session_resource import register_session_resource
    from dsh.fs.fs_local import FsLocalPlugin
    from dsh.host.connection.peer import Peer
    ctx = Context(); abort = AbortController(); primary = RuntimeError('query failed'); fail = [False]
    try:
        for plugin in (CurrentTypertRegistry, RemoteAccessService, AuthorizedGatewayCore): await ctx.plugin(plugin)
        await ctx.plugin(FsLocalPlugin, dict(cwd=str(tmp_path))); register_session_resource(ctx)
        async def applications(path, signal):
            if fail[0]: raise primary
            return [dict(id='app', name='Editor', default=True, icon=None)]
        api = AuthorizedSessionController(ctx, dict(nativeOpen=True), dict(fileApplications=applications))
        ctx.remoteAccess.registerPolicy('guest', dict(bindings=lambda *_:[dict(resource=dict(kind='global'), role=dict(actions=['session/workspacePathApplications']))]))
        peer = Peer(ctx, dict(principal=dict(kind='guest', id='guest')))
        def call(method): return dict(namespace='session', method=method, args=dict(request=dict(path=str(tmp_path/'file.txt'))), peer=peer, signal=abort.signal)
        assert (await ctx.typertGateway.invoke(call('workspacePathApplications')))[0]['id'] == 'app'
        with pytest.raises(RemoteError) as caught: await ctx.typertGateway.invoke(call('openWorkspacePath'))
        assert caught.value.code == 'remote-access/denied'
        fail[0] = True
        with pytest.raises(RemoteError) as caught: await ctx.typertGateway.invoke(call('workspacePathApplications'))
        assert caught.value.code == 'gateway/internal' and caught.value.cause is primary
        abort.abort()
        with pytest.raises(RemoteError) as caught: await ctx.typertGateway.invoke(call('workspacePathApplications'))
        assert caught.value.code == 'gateway/cancelled'
    finally: abort.abort(); await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != 'win32', reason='Actual private Windows Shell association')
async def test_actual_windows_registered_handler_and_ps2_serializer_path(tmp_path):
    import winreg
    suffix = uuid.uuid4().hex; extension = '.dsh' + suffix; prog_id = 'DSH.Test.' + suffix
    executable = tmp_path / ('dsh-handler-' + suffix + '.exe'); marker = tmp_path / 'opened.txt'
    file = tmp_path / ("\u6d4b\u8bd5 ' audio" + extension); file.write_text('test', encoding='utf-8')
    controller = AbortController(); scripts = []; process_handle = None
    def literal(text): return "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{}'))".format(base64.b64encode(text.encode('utf-8')).decode('ascii'))
    source = 'using System; using System.IO; using System.Diagnostics; public static class Handler { public static void Main(string[] args) { File.WriteAllLines(' + json.dumps(str(marker)) + ', new string[] { args[0], Process.GetCurrentProcess().Id.ToString() }); } }'
    compile_script = "$ErrorActionPreference = 'Stop'\nAdd-Type -ReferencedAssemblies System -OutputType ConsoleApplication -OutputAssembly (" + literal(str(executable)) + ") -TypeDefinition @'\n" + source + "\n'@\n"
    keys = ['Software\\Classes\\' + extension, 'Software\\Classes\\' + prog_id, 'Software\\Classes\\Applications\\' + executable.name]
    def put(key, name, value):
        assert any(key == owned or key.startswith(owned + '\\') for owned in keys)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle: winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
    def remove(key):
        assert any(key == owned or key.startswith(owned + '\\') for owned in keys)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | winreg.KEY_WRITE) as handle:
                while True:
                    try: child = winreg.EnumKey(handle, 0)
                    except OSError: break
                    remove(key + '\\' + child)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError: pass
    async def run(command, args, signal):
        if command == 'powershell.exe' and '-File' in args: scripts.append(Path(args[-1]))
        return await run_native_command(command, args, signal)
    try:
        await run('powershell.exe', ['-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(compile_script.encode('utf-16-le')).decode('ascii')], controller.signal)
        command = '"{}" "%1"'.format(executable)
        put(keys[0], '', prog_id); put(keys[0] + r'\OpenWithProgids', prog_id, '')
        put(keys[1] + r'\shell\open\command', '', command)
        put(keys[2] + r'\shell\open\command', '', command); put(keys[2] + r'\SupportedTypes', extension, '')
        applications = await native_file_applications(str(file), controller.signal, dict(run=run))
        selected = next(app for app in applications if app['id'].lower() == str(executable).lower())
        assert selected['default'] and isinstance(selected['name'], str)
        async def legacy(command, args, signal):
            script = Path(args[-1]); text = script.read_text(encoding='utf-8')
            script.write_text(text.replace('if (Get-Command ConvertTo-Json -ErrorAction SilentlyContinue)', 'if ($false)'), encoding='utf-8')
            return await run(command, args, signal)
        assert await native_file_applications(str(file), controller.signal, dict(run=legacy)) == applications
        await open_native_file_application(str(file), selected['id'], controller.signal, dict(run=run))
        async def received():
            while True:
                try:
                    lines = marker.read_text(encoding='utf-8').splitlines()
                    if len(lines) == 2: return lines
                except FileNotFoundError: pass
                await asyncio.sleep(.01)
        lines = await asyncio.wait_for(received(), 5)
        assert os.path.samefile(lines[0], str(file))
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD); kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD); kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        process_handle = kernel.OpenProcess(0x00100000 | 1, False, int(lines[1]))
        if process_handle:
            assert await asyncio.get_running_loop().run_in_executor(None, kernel.WaitForSingleObject, process_handle, 5000) == 0
        with pytest.raises(RuntimeError, match='Application is not registered'):
            await open_native_file_application(str(file), 'not-registered', controller.signal, dict(run=run))
        assert scripts and all(not path.exists() and not path.parent.exists() for path in scripts)
    finally:
        controller.abort()
        if process_handle:
            if kernel.WaitForSingleObject(process_handle, 0) != 0:
                kernel.TerminateProcess(process_handle, 1); kernel.WaitForSingleObject(process_handle, 5000)
            kernel.CloseHandle(process_handle)
        for key in keys: remove(key)
