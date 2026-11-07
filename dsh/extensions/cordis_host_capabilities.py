"""Cooperative Python closure for dynamic Host source, not a security sandbox.

Ordinary file/network/process/timer acquisition belongs to Context services.
Only computation modules and selected async coordination primitives are exposed.
Framework code keeps normal Python imports and builtins.
"""
import asyncio
import builtins
import importlib
import sys
from types import ModuleType, SimpleNamespace

from dsh.core.session.json import UNDEFINED


MODULE_MEMBERS = {
    'math': None, 'cmath': None, 'decimal': None, 'fractions': None,
    'statistics': None, 'itertools': None, 'functools': None, 'operator': None,
    'collections': ('Counter', 'OrderedDict', 'defaultdict', 'deque', 'namedtuple', 'ChainMap'),
    'json': ('dumps', 'loads', 'JSONDecodeError', 'JSONEncoder', 'JSONDecoder'),
    're': ('compile', 'escape', 'findall', 'finditer', 'fullmatch', 'match', 'search', 'split',
           'sub', 'subn', 'error', 'A', 'ASCII', 'I', 'IGNORECASE', 'L', 'LOCALE', 'M',
           'MULTILINE', 'S', 'DOTALL', 'U', 'UNICODE', 'X', 'VERBOSE'),
    'base64': ('b64encode', 'b64decode', 'urlsafe_b64encode', 'urlsafe_b64decode',
               'b32encode', 'b32decode', 'b16encode', 'b16decode', 'a85encode', 'a85decode', 'b85encode', 'b85decode'),
    'binascii': ('hexlify', 'unhexlify', 'crc32', 'a2b_base64', 'b2a_base64', 'Error'),
    'hashlib': ('md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512', 'blake2b', 'blake2s',
                'sha3_224', 'sha3_256', 'sha3_384', 'sha3_512', 'shake_128', 'shake_256', 'new', 'pbkdf2_hmac'),
    'hmac': ('new', 'digest', 'compare_digest'),
    'datetime': ('date', 'datetime', 'time', 'timedelta', 'timezone', 'tzinfo', 'MINYEAR', 'MAXYEAR'),
    'time': ('time', 'time_ns', 'monotonic', 'monotonic_ns', 'perf_counter', 'perf_counter_ns',
             'gmtime', 'localtime', 'mktime', 'strftime', 'strptime', 'struct_time',
             'timezone', 'altzone', 'daylight', 'tzname'),
    'asyncio': ('CancelledError', 'TimeoutError', 'Event', 'Lock', 'Condition', 'Semaphore',
                'BoundedSemaphore', 'Queue', 'PriorityQueue', 'LifoQueue', 'QueueEmpty', 'QueueFull',
                'create_task', 'gather', 'shield', 'wait', 'as_completed', 'current_task', 'isfuture',
                'iscoroutine', 'iscoroutinefunction'),
}
DENIED_BUILTINS = ('open', 'input', 'breakpoint', 'help', 'license', 'copyright', 'credits', 'exit', 'quit')
REDIRECT = ("Dynamic Python Host capability '{}' is unavailable. Use Context services: "
            "ctx.fs for files, ctx.web for network, the inspected shell service for processes, "
            "and ctx.timeout/ctx.interval after injecting timer. Query cordis_inspect_list/query first.")


def unavailable(name):
    def denied(*args, **kwargs):
        raise RuntimeError(REDIRECT.format(name))
    return denied


class ComputationModule(SimpleNamespace):
    def __getattr__(self, name):
        raise AttributeError(REDIRECT.format(self.__name__ + '.' + name))


async def yield_once(delay=0, result=None):
    if delay != 0:
        raise RuntimeError(REDIRECT.format('asyncio.sleep(delay)'))
    await asyncio.sleep(0)
    return result


def host_builtins(source_namespace):
    modules = {}
    def import_module(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in MODULE_MEMBERS:
            raise ImportError(REDIRECT.format('import ' + name))
        if name not in modules:
            module = importlib.import_module(name)
            names = MODULE_MEMBERS[name]
            if names is None:
                names = getattr(module, '__all__', [key for key in vars(module) if not key.startswith('_')])
                names = [key for key in names if not isinstance(getattr(module, key), ModuleType)]
            members = {key: getattr(module, key) for key in names}
            if name == 'asyncio':
                members['sleep'] = yield_once
            modules[name] = ComputationModule(__name__=name, **members)
        for member in fromlist or ():
            if member != '*' and member not in vars(modules[name]):
                raise ImportError(REDIRECT.format(name + '.' + member))
        return modules[name]
    result = dict(vars(builtins))
    result['__import__'] = import_module
    def evaluate(source, globals=None, locals=None):
        frame = sys._getframe(1)
        authored_caller = frame.f_globals.get('__builtins__') is result
        namespace = (frame.f_globals if authored_caller else source_namespace) if globals is None else globals
        local_namespace = (frame.f_locals if globals is None and authored_caller else namespace) if locals is None else locals
        namespace['__builtins__'] = result
        return builtins.eval(source, namespace, local_namespace)
    def execute(source, globals=None, locals=None):
        frame = sys._getframe(1)
        authored_caller = frame.f_globals.get('__builtins__') is result
        namespace = (frame.f_globals if authored_caller else source_namespace) if globals is None else globals
        local_namespace = (frame.f_locals if globals is None and authored_caller else namespace) if locals is None else locals
        namespace['__builtins__'] = result
        return builtins.exec(source, namespace, local_namespace)
    result['eval'], result['exec'] = evaluate, execute
    for name in DENIED_BUILTINS:
        result[name] = unavailable(name)
    return result


def host_namespace(harness):
    namespace = dict(harness=harness, UNDEFINED=UNDEFINED, __name__='__cordis_host__')
    namespace['__builtins__'] = host_builtins(namespace)
    return namespace
