"""
Ownership of one unpublished Session before registry publication.
Ported 1:1 from reference packages/core/session/src/preparation.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Callable, Optional, Union


class SessionPreparation:
    """
    One exact unpublished Session and the provider state that keeps it usable.
    Disposal is synchronous and idempotent. Providers decide whether release
    returns the Session to a cache or discards it; publication may consume that
    state before disposal, making the callback a no-op.
    """

    def __init__(self, session: Any, release: Optional[Callable[[], None]] = None):
        self._session = session
        self._release = release
        self._released = False

    @property
    def session(self) -> Any:
        """The exact Session to use for setup and publication."""
        return self._session

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    @classmethod
    def create(cls, session: Any, options: Optional[Any] = None) -> "SessionPreparation":
        """
        Wrap an unpublished Session in one preparation lifetime.
        """
        if isinstance(session, SessionPreparation):
            return session
        release_cb = None
        if isinstance(options, dict):
            release_cb = options.get("release")
        elif callable(options):
            release_cb = options
        return cls(session=session, release=release_cb)

    def dispose(self) -> None:
        """Release provider state once when this preparation leaves its caller."""
        if self._released:
            return
        self._released = True
        if self._release is not None:
            self._release()

    def close(self) -> None:
        self.dispose()

    def __enter__(self) -> "SessionPreparation":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.dispose()
