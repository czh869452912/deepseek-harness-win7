"""Experimental SDK adapter for an exported native dynamic Host source body.

Each Loader mount evaluates fresh globals and mounts the original guarded plugin
as a Cordis child. This is trusted Python execution, not a security sandbox.
"""
import inspect
import hashlib
import sys
import time
from types import SimpleNamespace

from dsh.extensions.cordis_guard import (clone_json, guarded_plugin,
    normalize_handler, sandbox_define_tool, sandbox_register_tool)
from dsh.typert.remote import Remote, TypertRemoteService


def host_handler_service(package_name):
    return 'pythonPlugin:' + package_name


def host_remote_namespace(package_name):
    return 'pythonExport' + hashlib.sha256(package_name.encode('utf-8')).hexdigest()[:24]


class ExportedHostRemote(TypertRemoteService):
    def __init__(self, ctx, package_name, handlers):
        super().__init__(ctx, host_remote_namespace(package_name))
        self._handlers = handlers

    @Remote
    async def call(self, method, args):
        return await self._handlers.call(method, args)


class PythonHostHandlers:
    def __init__(self):
        self.handlers = {}
        self.closed = False
        self.active = False
        self.activation = 0

    def handle(self, method, callback):
        if self.closed:
            raise RuntimeError('exported Python Host is unloaded')
        method, normalized = normalize_handler(method, callback)
        self.handlers[method] = normalized
        def dispose():
            if self.handlers.get(method) is normalized:
                del self.handlers[method]
        return dispose

    async def call(self, method, args):
        if self.closed or not self.active:
            raise RuntimeError('exported Python Host is unloaded')
        callback = self.handlers.get(method)
        if callback is None:
            raise ValueError('unknown exported Host handler: ' + method)
        activation = self.activation
        value = await callback(clone_json(args, 'exported Host handler arguments'))
        if self.closed or not self.active or self.activation != activation:
            raise RuntimeError('exported Python Host activation ended during the call')
        return value

    def activate(self):
        if self.closed:
            raise RuntimeError('exported Python Host is unloaded')
        self.activation += 1
        self.active = True

    def close(self):
        self.closed = True
        self.active = False
        self.handlers.clear()

    def deactivate(self):
        self.active = False


def python_host_source(source_path, package_name, enable_remote=False):
    """Return a reusable Loader entry; globals and registrations are per mount."""
    async def apply(ctx, config=None):
        handlers = PythonHostHandlers()
        ctx.effect(lambda: handlers.close, 'exported Host handlers')
        if source_path is None:
            source = 'def plugin(ctx):\n    pass\n'
        else:
            with open(source_path, encoding='utf-8', newline='') as stream:
                source = stream.read()
        namespace = dict(__file__=source_path, harness=SimpleNamespace(
            handle=handlers.handle, defineTool=sandbox_define_tool,
            registerTool=sandbox_register_tool))
        deadline, previous = time.monotonic() + 5.0, sys.gettrace()
        def trace(frame, event, arg):
            if time.monotonic() > deadline:
                raise TimeoutError('exported Host evaluation exceeded 5000 ms')
            return trace
        try:
            sys.settrace(trace)
            exec(compile(source, source_path or '<exported-client-only>', 'exec'), namespace)
        finally:
            sys.settrace(previous)
        native = namespace.get('plugin')
        if not callable(native) and not (isinstance(native, dict) and callable(native.get('apply'))):
            raise ValueError('Python Host code must expose a callable plugin or a plugin dict with apply(ctx)')
        def report(error):
            # The guard already raises at the offending access. No Agent from
            # the originating dynamic session is retained in the installed SDK.
            pass
        guarded = guarded_plugin(native, report)
        callback = guarded['apply']
        async def activate(child_ctx, child_config=None):
            handlers.activate()
            child_ctx.effect(lambda: handlers.deactivate, 'exported Host activation')
            child_ctx.provide(host_handler_service(package_name), handlers)
            if enable_remote:
                ExportedHostRemote(child_ctx, package_name, handlers)
            returned = callback(child_ctx, child_config)
            if inspect.isawaitable(returned):
                returned = await returned
            return returned
        guarded['apply'] = activate
        fiber = ctx.plugin(guarded, config)
        try:
            missing = [name for name in fiber.inject if fiber.ctx.get(name) is None]
            if missing:
                raise ValueError('exported Python Host requires services: ' + ', '.join(missing))
            await fiber
        except BaseException:
            await fiber.dispose()
            raise
    apply.name = package_name
    return apply
