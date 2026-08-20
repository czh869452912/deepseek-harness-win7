import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple


class EventBus:
    """
    Cordis Event Bus supporting emit, waterfall, parallel, and serial dispatch modes.
    """

    def __init__(self):
        self._listeners: Dict[str, List[Callable[..., Any]]] = {}

    def on(self, event_name: str, handler: Callable[..., Any], prepend: bool = False) -> Callable[[], None]:
        """
        Register an event handler. Returns a disposer function to unregister.
        """
        if event_name not in self._listeners:
            self._listeners[event_name] = []

        if prepend:
            self._listeners[event_name].insert(0, handler)
        else:
            self._listeners[event_name].append(handler)

        def disposer():
            if event_name in self._listeners and handler in self._listeners[event_name]:
                self._listeners[event_name].remove(handler)

        return disposer

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Emit event synchronously to listeners.
        """
        listeners = list(self._listeners.get(event_name, []))
        for listener in listeners:
            try:
                res = listener(*args, **kwargs)
                if inspect.isawaitable(res):
                    # Create task for async listeners in sync emit context
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception as e:
                print(f"[Cordis Event Error] Exception in emit '{event_name}': {e}")

    async def emit_async(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Emit event asynchronously to listeners in sequence.
        """
        listeners = list(self._listeners.get(event_name, []))
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                await res

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        """
        Parallel dispatch: run all listeners concurrently using asyncio.gather.
        """
        listeners = list(self._listeners.get(event_name, []))
        tasks = []
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                tasks.append(res)
            else:
                async def _wrap(val=res):
                    return val
                tasks.append(_wrap())

        if not tasks:
            return []
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def serial(self, event_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        """
        Serial dispatch: run listeners sequentially awaiting each.
        """
        listeners = list(self._listeners.get(event_name, []))
        results = []
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                res = await res
            results.append(res)
        return results

    async def waterfall(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Waterfall middleware pipeline.
        Listeners are called with (data, *args, next_fn).
        Calling next_fn(modified_data) invokes downstream listeners.
        Short-circuiting occurs if next_fn is not called.
        """
        listeners = list(self._listeners.get(event_name, []))

        async def run_pipeline(index: int, current_data: Any) -> Any:
            if index >= len(listeners):
                return current_data

            listener = listeners[index]

            async def next_fn(next_data: Any = None) -> Any:
                payload = current_data if next_data is None else next_data
                return await run_pipeline(index + 1, payload)

            # Check if listener signature expects next_fn
            sig = inspect.signature(listener)
            params = list(sig.parameters.keys())
            
            # If listener expects next_fn parameter
            if len(params) >= len(args) + 2:
                res = listener(current_data, *args, next_fn, **kwargs)
            else:
                # Listener modifies data directly or returns modified data
                res = listener(current_data, *args, **kwargs)
                if inspect.isawaitable(res):
                    res = await res
                if res is not None:
                    return await next_fn(res)
                return await next_fn(current_data)

            if inspect.isawaitable(res):
                res = await res
            return res

        return await run_pipeline(0, data)
