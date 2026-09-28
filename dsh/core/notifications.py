"""Contained scoped notifications: one observer cannot starve its peers."""
import asyncio
import inspect
import logging

from dsh.core.scope import scope_of, scope_target

logger = logging.getLogger(__name__)


def emit_contained(ctx, name, payload, subject=None, base=None):
    carrier = scope_target(base or subject, scope_of(subject.ctx)) if subject is not None else ctx
    for callback in ctx.events.dispatch("emit", [carrier, name, payload]):
        try:
            returned = callback(payload)
            if inspect.isawaitable(returned):
                async def settle(result):
                    try:
                        await result
                    except Exception:
                        logger.warning("%s listener rejected", name, exc_info=True)
                asyncio.ensure_future(settle(returned))
        except Exception:
            logger.warning("%s listener threw", name, exc_info=True)
