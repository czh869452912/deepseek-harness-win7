"""Experimental SDK adapter for an exported native dynamic Host source body.

Each Loader mount evaluates fresh globals and mounts the original guarded plugin
as a Cordis child. This is trusted Python execution, not a security sandbox.
"""
import ast
import inspect
import hashlib
import sys
import time
from types import SimpleNamespace
from weakref import WeakKeyDictionary

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


class ExportedSessionRemote(TypertRemoteService):
    """Host routing only; authored code belongs to the addressed preset."""
    def __init__(self, ctx, package_name):
        super().__init__(ctx, host_remote_namespace(package_name))
        self._handler_service = host_handler_service(package_name)

    def _handlers(self, agent):
        return self.ctx.get('agentPresets').serviceFor(agent, self._handler_service)

    @Remote
    def available(self, agent):
        handlers = self._handlers(agent)
        return handlers is not None and handlers.active and not handlers.closed

    @Remote
    async def call(self, agent, method, args):
        handlers = self._handlers(agent)
        if handlers is None:
            raise RuntimeError('exported Session Host is not mounted for this Agent')
        return await handlers.call(method, args)


def python_session_source(source_path, package_name):
    """Compose an installed bridge and the independently mounted preset half."""
    host = python_host_source(source_path, package_name)
    async def apply(ctx, config=None):
        if isinstance(config, dict) and config.get('sessionClientBridge') is True:
            ExportedSessionRemote(ctx, package_name)
        else:
            await host(ctx, config)
    apply.name = package_name
    apply.inject = ['agentPresets']
    return apply


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


def _source_inject_declaration(source_path):
    if source_path is None:
        return None
    try:
        with open(source_path, encoding="utf-8", newline="") as stream:
            tree = ast.parse(stream.read())
        final = tree.body[-1] if tree.body else None
        if not isinstance(final, ast.Assign) or len(final.targets) != 1:
            return None
        target = final.targets[0]
        if not isinstance(target, ast.Attribute) or target.attr != "inject" or not isinstance(target.value, ast.Name) or target.value.id != "plugin":
            return None
        declared = ast.literal_eval(final.value)
        if type(declared) not in (list, tuple) or any(type(name) is not str or not name for name in declared):
            return None
        return list(declared)
    except (OSError, SyntaxError, ValueError, TypeError, RecursionError):
        return None


def python_host_source(source_path, package_name, enable_remote=False):
    """Return a reusable Loader entry; globals and registrations are per mount."""
    declared = _source_inject_declaration(source_path)
    mounts = WeakKeyDictionary()
    async def apply(ctx, config=None):
        mounted = mounts.get(ctx.fiber)
        if mounted is None:
            handlers = PythonHostHandlers()
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
            if declared is not None and list(guarded.get('inject', [])) != declared:
                raise ValueError('exported Python Host dependency declaration changed after import')
            mounted = handlers, guarded
            mounts[ctx.fiber] = mounted
            owner = ctx.parent or ctx

            def close():
                handlers.close()
                mounts.pop(ctx.fiber, None)
                remove_observer()

            def disposed(fiber):
                if fiber is ctx.fiber and fiber.uid is None:
                    release()

            remove_observer = owner.on('internal/plugin', disposed)
            release = owner.effect(lambda: close, 'exported Host mount')
        handlers, definition = mounted
        guarded = dict(definition)
        ctx.effect(lambda: handlers.deactivate, 'exported Host handlers')
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
    if declared is not None:
        apply.inject = declared
    return apply
