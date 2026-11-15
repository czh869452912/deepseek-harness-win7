import asyncio
import socket
import threading

import pytest

from dsh.code_runtime.control import ControlListener, connect_control


@pytest.mark.asyncio
async def test_inherited_output_does_not_forge_protocol_and_remains_bounded(tmp_path):
    from scripts import rc022_ptc_control_probe as probe
    probe.WORKSPACE = tmp_path
    rows = {row['name']:row['result'] for row in await asyncio.wait_for(probe.observe(), 20)}
    assert rows['forged-output'] == dict(logs='{"type":"done","value":"forged"}\n', value=42)
    assert rows['stderr'] == dict(logs='错误🙂', value=True)
    assert rows['invalid-utf8'] == dict(logs='a�b', value=None)
    assert rows['raw-output-limit']['error'] == 'output-limit'


def test_control_rejects_an_unrelated_connection_and_closes_all_owned_sockets():
    owner = ControlListener()
    stopped = threading.Event()
    accepted = []
    thread = threading.Thread(target=lambda: accepted.append(owner.accept(stopped, lambda:False)))
    thread.start()
    connection = incoming = outgoing = None
    try:
        with socket.create_connection(('127.0.0.1', owner.spec['port'])) as wrong:
            wrong.sendall(b'wrong\n')
        connection, incoming, outgoing = connect_control(owner.spec)
        thread.join(2)
        assert not thread.is_alive() and accepted[0] is owner.incoming
        assert not connection.get_inheritable() and not owner.connection.get_inheritable()
        outgoing.write(b'payload\n')
        outgoing.flush()
        assert owner.incoming.readline() == b'payload\n'
        owner.close()
        owner.close()
        assert incoming.read() == b''
        with pytest.raises(OSError):
            socket.create_connection(('127.0.0.1', owner.spec['port']), timeout=.2)
    finally:
        stopped.set()
        owner.close()
        thread.join(2)
        for stream in (incoming, outgoing, connection):
            if stream is not None:
                stream.close()


def test_closing_a_listener_unblocks_an_unaccepted_worker():
    owner = ControlListener()
    stopped = threading.Event()
    errors = []
    def accept():
        try:
            owner.accept(stopped, lambda:False)
        except OSError as error:
            errors.append(error)
    thread = threading.Thread(target=accept)
    thread.start()
    stopped.set()
    owner.close()
    thread.join(2)
    assert not thread.is_alive()


@pytest.mark.asyncio
async def test_completion_reaps_a_descendant_holding_inherited_output(tmp_path):
    import json
    from dsh.cordis import Context
    from dsh.code_runtime.ptc import PythonPtcRuntime
    ctx = Context()
    await ctx.plugin(PythonPtcRuntime, dict(timeoutMs=5000))
    runtime = ctx.get('ptcRuntime')
    child = "import time;time.sleep(60)"
    program = ('import subprocess,sys\n'
               'child=subprocess.Popen([sys.executable,"-c",%s])\n'
               'return child.pid' % json.dumps(child))
    try:
        result = await asyncio.wait_for(runtime.run(runtime.resolve(dict(program=program,
            bindings=[], cwd=str(tmp_path)))), 4)
        assert 'error' not in result and type(result['value']) is int
        assert not runtime.runs
        if __import__('os').name == 'nt':
            import ctypes
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.OpenProcess.restype = ctypes.c_void_p
            handle = api.OpenProcess(0x1000, False, result['value'])
            if handle:
                try:
                    code = ctypes.c_ulong()
                    assert api.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
                    assert code.value != 259
                finally:
                    api.CloseHandle(ctypes.c_void_p(handle))
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_legacy_worker_boot_uses_utf8_instead_of_windows_console_encoding():
    from dsh.cordis import Context
    from dsh.code_runtime.process import PythonProcessRuntime
    ctx = Context()
    await ctx.plugin(PythonProcessRuntime)
    try:
        result = await ctx.get('codeRuntime').run(dict(
            program="print('你好🙂')\nreturn '错误🙂'", bindings=[]))
        assert result == dict(logs=['你好🙂'], value='错误🙂')
    finally:
        await ctx.fiber.dispose()
