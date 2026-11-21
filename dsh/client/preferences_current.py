"""Live Loader forms consumed by the pinned chat and conversation clients."""
from dsh.client.ui_conversation import BUSY_ENTER_BEHAVIORS, DEFAULT_BUSY_ENTER_BEHAVIOR
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z


class _ClientPreferences(Plugin):
    def apply(self, ctx):
        def configure(child):
            child.effect(lambda: child.get('settings').configure({'auto': False}, ctx.fiber))
        ctx.inject(['settings'], configure)


class CurrentDeveloperTools(_ClientPreferences):
    Config = z.object(dict(enabled=z.boolean().default(True).volatile()))


class CurrentConversation(_ClientPreferences):
    Config = z.object(dict(busyEnter=z.union(list(BUSY_ENTER_BEHAVIORS))
                           .default(DEFAULT_BUSY_ENTER_BEHAVIOR).volatile()))


class CurrentChat(_ClientPreferences):
    Config = z.object(dict(
        transcriptView=z.union(['compact', 'standard', 'detailed', 'verbose', 'normal', 'expanded']).loose().volatile(),
        collapseTiming=z.union(['completion', 'next-input']).default('completion').volatile(),
        foldedReplies=z.union(['all', 'final']).default('all').volatile(),
        performanceUsage=z.union(['compact', 'detailed']).default('detailed').volatile(),
        linkOpening=z.union(['sidebar', 'new-tab']).default('sidebar').volatile(),
    ))
