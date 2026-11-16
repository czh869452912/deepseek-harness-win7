"""Stable per-Fiber MCP status and independent generation-closure observations."""
import asyncio
import inspect
from dsh.cordis.awaiting import start_coroutine


class McpStatusCell:
    def __init__(self, warn):
        self._value = dict(state='connecting',attempt=0)
        self._closure = dict(closeConfirmed=True)
        self._warn = warn
        self._listeners = {}
        self._observers = set()

    def current(self):
        return self._value

    def closure(self):
        return self._closure

    def opened(self):
        self._closure = dict(closeConfirmed=False)

    def recordClosure(self, result):
        self._closure = result

    def detach(self):
        self._listeners.clear()

    def setWarningSink(self, warn):
        self._warn = warn

    def onChange(self, callback):
        identity = id(callback)
        self._listeners[identity] = callback
        def dispose():
            self._listeners.pop(identity,None)
        return dispose

    def update(self, next_status):
        self._value = next_status
        for listener in list(self._listeners.values()):
            try:
                returned = listener(next_status)
                if inspect.isawaitable(returned):
                    task = start_coroutine(returned) if inspect.iscoroutine(returned) else asyncio.ensure_future(returned)
                    self._observers.add(task)
                    def settled(completed):
                        self._observers.discard(completed)
                        if not completed.cancelled():
                            error = completed.exception()
                            if error is not None:
                                self._warn('an onChange status observer failed',error)
                    task.add_done_callback(settled)
            except Exception as error:
                self._warn('an onChange status observer failed',error)


def register_status_cell(fiber, warn):
    # Fiber-owned storage gives Python the same lifetime as the Source WeakMap
    # without a global value -> warning sink -> Fiber retention cycle.
    cell = fiber.__dict__.get('_dsh_mcp_status_cell')
    if cell is None:
        cell = fiber._dsh_mcp_status_cell = McpStatusCell(warn)
    else:
        cell.setWarningSink(warn)
    return cell


def connection_status_in(fiber):
    return fiber.ctx.fiber.__dict__.get('_dsh_mcp_status_cell')
