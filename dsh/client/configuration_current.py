"""Validated configuration globals supplied by current browser Host companions."""
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z


class CurrentShortcutsHost(Plugin):
    Config = z.object(dict(stopSequenceMs=z.natural().min(1).max(2147483646).default(500)))

    def apply(self, ctx):
        ctx.on('webserver/index-inject', lambda table, *args: table.append(dict(kind='global', name='__DSH_SHORTCUTS_CONFIG__', value=self.config)))


class CurrentDocumentPreviewHost(Plugin):
    Config = z.object(dict(
        office=z.object(dict(
            maxCachedEntries=z.natural().min(1).max(9007199254740991).default(8),
            maxCachedBytes=z.natural().min(1).max(9007199254740991).default(64*1024*1024),
            maxPending=z.natural().min(1).max(9007199254740991).default(8),
            maxReaders=z.natural().min(1).max(9007199254740991).default(32))),
        excel=z.object(dict(
            maxBytes=z.natural().min(1).max(9007199254740991).default(16*1024*1024),
            maxCells=z.natural().min(1).max(9007199254740991).default(250000),
            timeoutMs=z.natural().min(1).max(2147483647).default(15000)))))

    def apply(self, ctx):
        ctx.on('webserver/index-inject', lambda table, *args: table.append(dict(kind='global', name='__DSH_DOCUMENT_PREVIEW_CONFIG__', value=self.config)))
