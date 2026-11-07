"""Private, bidirectional object bridge for a single dynamic Host process.

The parent owns Cordis contexts and effects. The child owns Python closures for
the whole Run. This is a lifetime boundary, not hostile-code containment.
"""
import asyncio
import builtins
from collections.abc import Iterable, Iterator, AsyncIterator
import inspect
import importlib
import pickle
import queue
import threading
import time
import traceback

from dsh.core.session.json import UNDEFINED


class RemoteObject:
    def __init__(self, peer, key, descriptor):
        object.__setattr__(self, '_peer', peer)
        object.__setattr__(self, '_key', key)
        object.__setattr__(self, '_descriptor', descriptor)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return self._peer.call('getattr', self, name)

    def __setattr__(self, name, value):
        self._peer.call('setattr', self, name, value)

    def __getitem__(self, key):
        return self._peer.call('getitem', self, key)

    def __setitem__(self, key, value):
        self._peer.call('setitem', self, key, value)

    def __contains__(self, key):
        return self._peer.call('contains', self, key)

    def __bool__(self):
        return self._peer.call('bool', self)

    def __len__(self):
        return self._peer.call('len', self)


class RemoteCallable(RemoteObject):
    def __call__(self, *args, **kwargs):
        return self._peer.call('call', self, args, kwargs)

    @property
    def __signature__(self):
        parameters = []
        for name, kind, optional in self._descriptor.get('signature', []):
            parameters.append(inspect.Parameter(name, kind, default=None if optional else inspect.Parameter.empty))
        return inspect.Signature(parameters)


class RemoteAwaitable(RemoteObject):
    def __await__(self):
        return self._peer.acall('await', self).__await__()


class RemoteCallableAwaitable(RemoteCallable, RemoteAwaitable):
    pass


class RemoteIterator(RemoteObject):
    def __iter__(self):
        return self

    def __next__(self):
        return self._peer.call('next', self)


class RemoteIterable(RemoteObject):
    def __iter__(self):
        return self._peer.call('iterate', self)


class RemoteAsyncIterator(RemoteObject):
    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._peer.call('anext', self)


class Peer:
    def __init__(self, incoming, outgoing, side):
        self.incoming, self.outgoing, self.side = incoming, outgoing, side
        self.messages, self.answers = queue.Queue(), {}
        self.objects, self.identities, self.descriptors = {}, {}, {}
        self.containers, self.sent = {}, {}
        self.serial, self.requests = 0, 0
        self.closed = False
        self.lock = threading.Lock()
        self.tasks = set()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                self.messages.put(pickle.load(self.incoming))
        except (EOFError, OSError, ValueError):
            self.messages.put(None)

    def _reference(self, value, definitions):
        identity = id(value)
        key = self.identities.get(identity)
        if key is None:
            self.serial += 1
            key = '{}:{}'.format(self.side, self.serial)
            self.identities[identity] = key
            self.objects[key] = value
        if key not in self.descriptors:
            self.descriptors[key] = dict(callable=callable(value), awaitable=inspect.isawaitable(value),
                                         iterator=isinstance(value, Iterator), async_iterator=isinstance(value, AsyncIterator),
                                         iterable=isinstance(value, Iterable))
            if callable(value):
                try:
                    signature = inspect.signature(value)
                except (ValueError, TypeError):
                    signature = None
                if signature is not None:
                    self.descriptors[key]['signature'] = [
                        (p.name, p.kind, p.default is not inspect.Parameter.empty)
                        for p in signature.parameters.values()]
        definitions[key] = self.descriptors[key]
        return ('ref', key)

    def pack(self, value):
        definitions, patches = {}, {}

        def encode(item):
            if item is UNDEFINED:
                return ('undefined',)
            if item is None or type(item) in (str, bool, int, float, bytes):
                return ('scalar', item)
            if isinstance(item, RemoteObject) and item._peer is self:
                return ('ref', item._key)
            if type(item) is tuple:
                return ('tuple', tuple(encode(child) for child in item))
            if type(item) in (dict, list):
                identity = id(item)
                key = self.identities.get(identity)
                if key is None:
                    self.serial += 1
                    key = '{}:{}'.format(self.side, self.serial)
                    self.identities[identity] = key
                    self.objects[key] = item
                    self.containers[key] = item
                definitions[key] = dict(container='dict' if type(item) is dict else 'list')
                return ('ref', key)
            return self._reference(item, definitions)

        root = encode(value)
        visited = set()
        # Include mutations of shared state even when a callback returns None.
        # Only changed keys/items are sent, so concurrent callbacks do not
        # replace an unrelated mutation with an older complete snapshot.
        while True:
            pending = [(key, item) for key, item in self.containers.items() if key not in visited]
            if not pending:
                break
            for key, item in pending:
                visited.add(key)
                kind = 'dict' if type(item) is dict else 'list'
                definitions[key] = dict(container=kind)
                current = ([(encode(k), encode(v)) for k, v in item.items()] if kind == 'dict'
                           else [encode(v) for v in item])
                previous = self.sent.get(key)
                if previous != current:
                    if kind == 'dict' and previous is not None:
                        old, new = dict(previous), dict(current)
                        patches[key] = dict(set=[(k, v) for k, v in current if k not in old or old[k] != v],
                                            delete=[k for k in old if k not in new])
                    else:
                        patches[key] = dict(replace=current)
                    self.sent[key] = current
        return dict(root=root, definitions=definitions, patches=patches)

    def unpack(self, packet):
        for key, descriptor in packet['definitions'].items():
            if key in self.objects:
                continue
            kind = descriptor.get('container')
            if kind:
                value = {} if kind == 'dict' else []
                self.containers[key] = value
            else:
                cls = (RemoteCallableAwaitable if descriptor['callable'] and descriptor['awaitable']
                       else RemoteCallable if descriptor['callable'] else RemoteAwaitable if descriptor['awaitable']
                       else RemoteAsyncIterator if descriptor.get('async_iterator')
                       else RemoteIterator if descriptor.get('iterator')
                       else RemoteIterable if descriptor.get('iterable') else RemoteObject)
                value = cls(self, key, descriptor)
            self.objects[key] = value
            self.identities[id(value)] = key
            self.descriptors[key] = descriptor

        for key, descriptor in packet['definitions'].items():
            if 'dynamic_tool' in descriptor and isinstance(self.objects[key], RemoteObject):
                from dsh.extensions.cordis_guard import sandbox_define_tool
                value = sandbox_define_tool(self.unpack(descriptor['dynamic_tool']))
                self.objects[key] = value
                self.identities[id(value)] = key

        def decode(item):
            if item[0] == 'undefined':
                return UNDEFINED
            if item[0] == 'scalar':
                return item[1]
            if item[0] == 'tuple':
                return tuple(decode(child) for child in item[1])
            return self.objects[item[1]]

        for key, patch in packet['patches'].items():
            target = self.objects[key]
            if type(target) is dict:
                if 'replace' in patch:
                    target.clear()
                for k in patch.get('delete', []):
                    target.pop(decode(k), None)
                target.update((decode(k), decode(v)) for k, v in patch.get('replace', patch.get('set', [])))
                self.sent[key] = [(self._snapshot(k), self._snapshot(v)) for k, v in target.items()]
            else:
                target[:] = [decode(child) for child in patch['replace']]
                self.sent[key] = [self._snapshot(child) for child in target]
        return decode(packet['root'])

    def _snapshot(self, item):
        if item is UNDEFINED:
            return ('undefined',)
        if item is None or type(item) in (str, bool, int, float, bytes):
            return ('scalar', item)
        if type(item) is tuple:
            return ('tuple', tuple(self._snapshot(child) for child in item))
        return ('ref', self.identities[id(item)])

    def send(self, message):
        if self.closed:
            raise RuntimeError('dynamic Host process is closed')
        with self.lock:
            pickle.dump(message, self.outgoing, protocol=4)
            self.outgoing.flush()

    def request(self, op, args):
        self.requests += 1
        key = '{}-{}'.format(self.side, self.requests)
        self.send(dict(type='request', id=key, op=op, args=self.pack(args)))
        return key

    def call(self, op, *args):
        key = self.request(op, args)
        while key not in self.answers:
            if self.closed:
                raise RuntimeError('dynamic Host process is closed')
            self.dispatch(self.messages.get())
        return self.answer(key)

    async def acall(self, op, *args):
        key = self.request(op, args)
        while key not in self.answers:
            await self.pump()
        return self.answer(key)

    def answer(self, key):
        message = self.answers.pop(key)
        if 'error' in message:
            info = message['error']
            cls = getattr(builtins, info['name'], RuntimeError)
            if info['module'].startswith(('dsh.', 'asyncio')):
                try:
                    cls = getattr(importlib.import_module(info['module']), info['name'])
                except (ImportError, AttributeError):
                    pass
            if not isinstance(cls, type) or not issubclass(cls, BaseException):
                cls = RuntimeError
            error = cls.__new__(cls)
            BaseException.__init__(error, *self.unpack(info['args']))
            error.__dict__.update(self.unpack(info['attributes']))
            error.stack = info['stack']
            raise error
        return self.unpack(message['value'])

    async def pump(self):
        if self.closed:
            raise RuntimeError('dynamic Host process is closed')
        try:
            message = self.messages.get_nowait()
        except queue.Empty:
            await asyncio.sleep(.001)
        else:
            self.dispatch(message)

    def dispatch(self, message):
        if message is None:
            self.closed = True
            raise RuntimeError('dynamic Host process exited')
        if message['type'] == 'ready':
            self.ready = True
            return
        if message['type'] == 'evaluation-start':
            self.evaluation_started = time.monotonic()
            return
        if message['type'] == 'evaluation-finished':
            self.evaluation_duration = message['elapsedMs']
            return
        if message['type'] == 'answer':
            self.answers[message['id']] = message
            return
        args = self.unpack(message['args'])
        if message['op'] == 'await':
            task = asyncio.create_task(self._await_reply(message, args[0]))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return
        try:
            value = self.operation(message['op'], args)
        except BaseException as error:
            self.reply_error(message, error)
        else:
            self.send(dict(type='answer', id=message['id'], value=self.pack(value)))

    def operation(self, op, args):
        if op == 'call':
            target, positional, keywords = args
            return target(*positional, **keywords)
        if op == 'getattr':
            return getattr(*args)
        if op == 'setattr':
            return setattr(*args)
        if op == 'getitem':
            return args[0][args[1]]
        if op == 'setitem':
            args[0][args[1]] = args[2]
            return None
        if op == 'contains':
            return args[1] in args[0]
        if op == 'iterate':
            return iter(args[0])
        if op == 'next':
            return next(args[0])
        if op == 'anext':
            return args[0].__anext__()
        if op == 'bool':
            return bool(args[0])
        if op == 'len':
            return len(args[0])
        raise ValueError('unknown dynamic Host bridge operation: ' + op)

    async def _await_reply(self, request, value):
        try:
            result = await value
        except BaseException as error:
            self.reply_error(request, error)
        else:
            if not self.closed:
                self.send(dict(type='answer', id=request['id'], value=self.pack(result)))

    def reply_error(self, request, error):
        if self.closed:
            return
        stack = getattr(error, 'stack', None)
        if not isinstance(stack, str):
            stack = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        info = dict(name=type(error).__name__, module=type(error).__module__, message=str(error), stack=stack,
                    args=self.pack(error.args), attributes=self.pack({k: v for k, v in vars(error).items() if k != 'stack'}))
        self.send(dict(type='answer', id=request['id'], error=info))

    async def shutdown(self):
        self.closed = True
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        self.objects.clear()
        self.identities.clear()
        self.containers.clear()
        self.descriptors.clear()
        self.sent.clear()
        self.answers.clear()
