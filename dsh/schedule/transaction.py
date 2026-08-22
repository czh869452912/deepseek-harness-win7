"""
Agent-scoped serialization for Schedule reads and durable mutations.
1:1 parity with @deepseek-ai/dsh-schedule/transaction.ts
Python 3.8.10 compatible.
"""

import asyncio
from typing import Any, Callable, Dict, TypeVar, Awaitable
import weakref

T = TypeVar("T")

_locks: Dict[Any, asyncio.Lock] = weakref.WeakKeyDictionary()  # type: ignore


def _get_lock(agent: Any) -> asyncio.Lock:
    if agent not in _locks:
        _locks[agent] = asyncio.Lock()
    return _locks[agent]


async def run_schedule_transaction(agent: Any, operation: Callable[[], Awaitable[T]]) -> T:
    """Run one complete Schedule transaction after its exact Agent's prior transaction."""
    lock = _get_lock(agent)
    async with lock:
        return await operation()
