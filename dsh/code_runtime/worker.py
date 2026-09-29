"""Fresh-process Python bootstrap. Model code has shell-equivalent trust."""
import asyncio
import builtins
import json
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dsh.code_runtime.contract import snapshot_json, encoded


async def main():
    incoming, outgoing = sys.stdin, sys.stdout.buffer
    boot = json.loads(incoming.readline())
    # Windows' loader needs SystemRoot during interpreter initialization;
    # it is not part of the model program's environment.
    os.environ.clear()
    if os.name != 'nt':
        import resource
        cap = boot['memoryBytes']
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    loop = asyncio.get_running_loop()
    lock = threading.Lock()
    pending = {}
    serial = [0]

    def send(value):
        data = encoded(value) + b'\n'
        with lock:
            outgoing.write(data)
            outgoing.flush()

    def reply(value):
        future = pending.pop(value.get('id'), None)
        if future is not None and not future.done():
            future.set_result(value)

    def read():
        try:
            for line in incoming:
                value = json.loads(line)
                loop.call_soon_threadsafe(reply, value)
        except (OSError, ValueError, RuntimeError):
            pass

    send(dict(type='ready'))
    if json.loads(incoming.readline()).get('type') != 'start':
        return
    threading.Thread(target=read, daemon=True).start()

    def log(*values, **options):
        sep = options.get('sep', ' ')
        send(dict(type='log', text=sep.join(str(value) for value in values)))

    class Capture:
        def write(self, text):
            if text:
                send(dict(type='log', text=str(text)))
            return len(text)
        def flush(self):
            pass

    sys.stdout = sys.stderr = Capture()
    namespace = {'__builtins__': dict(vars(builtins), print=log), '__name__': '__dsh_program__',
                 'console': SimpleNamespace(log=log)}
    for binding in boot['bindings']:
        descriptor = binding.get('errorClass')
        error_type = type(descriptor['name'], (Exception,), {}) if descriptor else RuntimeError
        if descriptor:
            namespace[descriptor['name']] = error_type
        functions = {}
        for name in binding['functions']:
            async def call(args=None, _global=binding['global'], _name=name, _error=error_type, _descriptor=descriptor):
                args = snapshot_json(args)
                serial[0] += 1
                call_id = serial[0]
                future = loop.create_future()
                pending[call_id] = future
                send(dict(type='call', id=call_id, globalName=_global, name=_name, args=args))
                value = await future
                if 'error' in value:
                    error = _error(value['error'])
                    if _descriptor:
                        setattr(error, _descriptor['memberNameProperty'], _name)
                    raise error
                return value['value']
            functions[name] = call

        class Namespace:
            def __init__(self, values):
                object.__setattr__(self, '_values', values)
            def __getattribute__(self, name):
                values = object.__getattribute__(self, '_values')
                if name in values:
                    return values[name]
                return object.__getattribute__(self, name)
            def __getitem__(self, name):
                return object.__getattribute__(self, '_values')[name]

        namespace[binding['global']] = Namespace(functions)
    source = 'async def __dsh_main__():\n' + '\n'.join('    ' + line for line in boot['program'].splitlines()) + '\n'
    if not boot['program'].strip():
        source += '    pass\n'
    try:
        exec(compile(source, '<model-program>', 'exec'), namespace)
        value = await namespace['__dsh_main__']()
    except MemoryError:
        os._exit(87)
    except BaseException as error:
        send(dict(type='done', error=dict(kind='exception', message=str(error))))
        return
    try:
        value = snapshot_json(value)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        send(dict(type='done', error=dict(kind='invalid-output', message=str(error))))
        return
    send(dict(type='done', value=value))


if __name__ == '__main__':
    asyncio.run(main())
