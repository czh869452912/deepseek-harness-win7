"""Private Python 3.8 bootstrap; one process retains one dynamic Host Run."""
import asyncio
import copy
import json
import os
import sys
import time
from types import SimpleNamespace

sys.path[:0] = json.loads(os.environ.pop('DSH_CORDIS_HOST_PATH'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dsh.extensions.cordis_host_bridge import Peer
from dsh.extensions.cordis_guard import sandbox_define_tool, sandbox_register_tool


class HostPeer(Peer):
    def __init__(self, *args):
        super().__init__(*args)
        self.tool_options = {}
        self.exported_tools = set()
        self.pending_handlers, self.bound_handlers = {}, {}
        self.harness = None

    def _reference(self, value, definitions):
        result = super()._reference(value, definitions)
        options = self.tool_options.get(id(value))
        if options is not None and result[1] not in self.exported_tools:
            self.exported_tools.add(result[1])
            definitions[result[1]] = dict(self.descriptors[result[1]], dynamic_tool=self.pack(options))
        return result

    def define_tool(self, options):
        tool = sandbox_define_tool(options)
        self.tool_options[id(tool)] = copy.deepcopy(options)
        return tool

    def handle(self, method, handler):
        from dsh.extensions.cordis_guard import normalize_handler
        normalize_handler(method, handler)
        token = object()
        self.pending_handlers[method] = (token, handler)
        if self.harness is not None:
            self.bound_handlers[token] = self.harness.handle(method, handler)
        def dispose():
            if self.pending_handlers.get(method, (None,))[0] is token:
                del self.pending_handlers[method]
            bound = self.bound_handlers.pop(token, None)
            if bound is not None:
                bound()
        return dispose

    def operation(self, op, args):
        if op == 'evaluate':
            source, = args
            namespace = dict(harness=SimpleNamespace(handle=self.handle, defineTool=self.define_tool,
                registerTool=sandbox_register_tool), __name__='__cordis_host__')
            self.send(dict(type='evaluation-start'))
            start = time.monotonic()
            try:
                exec(compile(source, '<cordis-host>', 'exec'), namespace)
            finally:
                self.send(dict(type='evaluation-finished', elapsedMs=(time.monotonic() - start) * 1000))
            plugin = namespace.get('plugin')
            if not callable(plugin) and not (isinstance(plugin, dict) and callable(plugin.get('apply'))):
                raise ValueError('Python Host code must expose a callable plugin or a plugin dict with apply(ctx)')
            return dict(vars(plugin), apply=plugin) if callable(plugin) else plugin
        if op == 'bind-harness':
            self.harness, = args
            for method, (token, handler) in self.pending_handlers.items():
                self.bound_handlers[token] = self.harness.handle(method, handler)
            return None
        return super().operation(op, args)


async def main():
    peer = HostPeer(sys.stdin.buffer, sys.stdout.buffer, 'child')
    # Protocol traffic uses the original binary stream, never plugin stdout.
    sys.stdout = sys.stderr
    peer.send(dict(type='ready'))
    try:
        while not peer.closed:
            await peer.pump()
    finally:
        await peer.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
