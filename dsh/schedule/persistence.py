"""
Schedule-owned use of the shared session durability barrier.
1:1 parity with @deepseek-ai/dsh-schedule/persistence.ts
Python 3.8.10 compatible.
"""

from typing import Any, Optional


class SchedulePersistenceError(Exception):
    """Failure to prove that the current live prefix reached a persistence listener."""

    def __init__(self, cause: Optional[Exception] = None):
        msg = "Schedule persistence did not complete."
        super().__init__(msg)
        self.name = "SchedulePersistenceError"
        self.cause = cause


async def flush_schedule_persistence(ctx: Any, session: Any) -> None:
    """Require one successful shared persistence checkpoint."""
    try:
        sessions_svc = getattr(ctx, "sessions", None) if hasattr(ctx, "sessions") else ctx.get("sessions")
        if sessions_svc and hasattr(sessions_svc, "flush"):
            ok = await sessions_svc.flush(session)
            if not ok:
                raise SchedulePersistenceError()
        elif hasattr(ctx, "sessionPersistence") or (hasattr(ctx, "has") and ctx.has("sessionPersistence")):
            sp = ctx.get("sessionPersistence")
            if hasattr(sp, "flush"):
                ok = await sp.flush(session)
                if not ok:
                    raise SchedulePersistenceError()
    except SchedulePersistenceError as e:
        raise e
    except Exception as e:
        raise SchedulePersistenceError(cause=e)
