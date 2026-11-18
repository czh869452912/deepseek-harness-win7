"""Read-only persistence fixture over controlled listing/read callbacks.

Callbacks keep the selected fault and scheduling seams; consumers see only
the current list/open/read/close protocol, never historical persistence APIs.
"""
from types import SimpleNamespace


def read_fixture(list_headers, read_log=None):
    async def listing(options=None):
        signal = options.get('signal') if options else None
        return [dict(header=header, revision='controlled') for header in await list_headers(signal)]

    async def opened(session_id, mode, options=None):
        assert mode == 'read'
        signal = options.get('signal') if options else None
        loaded = await read_log(session_id, signal)
        field = loaded.get if isinstance(loaded, dict) else lambda key: getattr(loaded, key)
        closed = [False]
        async def read(start=0, options=None):
            assert not closed[0]
            return dict(events=field('events')[start:], eventState='detached')
        async def close():
            closed[0] = True
        return SimpleNamespace(header=field('meta'), inheritedEventCount=field('inheritedEventCount'), read=read, close=close)

    return SimpleNamespace(list=listing, open=opened)


from dsh.cordis.plugin import Plugin
from dsh.core.session.current_session import CurrentSessionStore


class SessionPluginV4(Plugin):
    """Mount the same current Session version as the pinned Source observer."""
    def apply(self, ctx):
        ctx.set_service('sessions', CurrentSessionStore(ctx, 4))


class ProjectionPluginV4(Plugin):
    def apply(self, ctx):
        from dsh.session.projections import SessionProjectionRegistry
        SessionProjectionRegistry(ctx, 4)
