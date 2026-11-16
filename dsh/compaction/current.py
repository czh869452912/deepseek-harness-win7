"""Compaction of v3 surfaces keeps the system head and replays it in history."""
from dsh.cordis.plugin import Plugin
from dsh.compaction.engine import CompactionEngine
from dsh.compaction.pruner import ToolResultPruner, ToolResultPrunerPlugin
from dsh.compaction.tool_pairing import tool_pairing_balanced_before


def select_compactable_range(session, measurement, retain_tokens=8000):
    nodes = list(session.surface.nodes)
    priced = measurement.get('nodes', [])
    if not priced:
        return None
    if nodes != [item['seq'] for item in priced]:
        raise ValueError('compaction: token-meter surface does not match the current session surface')
    first = 1 if session.eventAt(nodes[0])['type'] == 'system/message' else 0
    accumulated, keep = 0, len(priced)
    for index in range(len(priced)-1, -1, -1):
        accumulated += priced[index]['tokens']
        keep = index
        if accumulated >= retain_tokens:
            break
    if keep <= first:
        return None
    while keep > first and not tool_pairing_balanced_before(session, nodes[keep]):
        keep -= 1
    return dict(start=nodes[first], end=nodes[keep-1]) if keep > first else None


class CurrentCompactionEngine(CompactionEngine):
    summarization_fields = ('tools',)
    select_range = staticmethod(select_compactable_range)

    def summarization_input(self, session, selected):
        header = session.requestHeader() or {}
        messages = [session.deriveEventMessage(session.eventAt(seq)) for seq in selected]
        messages = [message for message in messages if message is not None]
        head = session.eventAt(session.surface.nodes[0])
        if head['type'] == 'system/message':
            system = session.deriveEventMessage(head)
            if system is not None:
                messages.insert(0, system)
        return dict(messages=messages, **(dict(tools=header['tools']) if 'tools' in header else {}))

    def replacement_surface(self, start, end):
        return dict(op='replace', startSeq=start, endSeq=end)

    async def recover_summary(self, error, agent, source_event_seqs, signal):
        return await self.ctx.waterfall('compaction/summary-error', dict(session=agent.session,
            sourceEventSeqs=source_event_seqs, error=error, signal=signal), lambda: False)


class CurrentCompactionBasic(Plugin):
    id = 'compaction-basic'
    inject = ['llm', 'tokenMeter', 'sessions']

    def apply(self, ctx):
        CurrentCompactionEngine(config=self.config, ctx=ctx)


class CurrentToolResultPruner(ToolResultPruner):
    def replacement_surface(self, seq):
        return dict(op='replace', startSeq=seq, endSeq=seq)


class CurrentToolResultPrunerPlugin(ToolResultPrunerPlugin):
    def apply(self, ctx):
        CurrentToolResultPruner(config=self.config, ctx=ctx)
