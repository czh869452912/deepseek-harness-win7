"""Pair actual region transactions with controlled summary/meter collaborators."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows = [dict(manual=manual, mutation=mutation, retry=retry)
            for manual in (True, False)
            for mutation in ('none', 'append', 'outside', 'rewrite', 'reprice')
            for retry in (True, False)]
    rows += [dict(manual=True, mutation='none', retry=True, extra=extra)
             for extra in ('cancel-recovery', 'cancel-summary', 'flush', 'large', 'busy', 'locked', 'stale')]
    rows += [dict(manual=False, mutation='none', retry=True, extra='no-turn')]
    return rows


def message(identity, text):
    return dict(id=identity, role='user', source=dict(kind='human'), content=[dict(type='text', text=text)])


def failure(error):
    result = dict(message=str(error))
    if hasattr(error, 'code'):
        result['code'] = error.code
    cause = getattr(error, 'cause', error.__cause__)
    if cause is not None:
        result['cause'] = failure(cause)
    return result


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.session.current_session import CurrentSession
    from dsh.compaction.current import CurrentCompactionEngine
    from dsh.compaction.transaction import compact
    rows = []
    for case in cases():
        ctx = Context()
        session = CurrentSession.create('session', format_version=4)
        session.append('user/message', message('selected', 'selected'), surface_op='append')
        session.append('user/message', message('outside', 'outside'), surface_op='append')
        extra = case.get('extra')
        if not case['manual'] and extra != 'no-turn' or extra == 'busy':
            session.append('turn/start', dict(turn=1))
        if extra == 'locked':
            session.append('compaction/start', dict(compactionId='held', turn=None))
        controller = AbortController()
        trace = []
        price = [100]
        calls = [0]
        class Meter:
            def measure(self, subject):
                nodes = [dict(seq=seq, tokens=price[0] if seq == 0 else 100, heuristicTokens=50)
                         for seq in subject.surface.nodes]
                if extra == 'stale':
                    nodes[0]['seq'] = 99
                return dict(nodes=nodes)
            def estimate_message(self, msg):
                return 100 if extra == 'large' else 1
        ctx.set_service('tokenMeter', Meter())
        engine = CurrentCompactionEngine(ctx=ctx)
        async def summarize(data, agent, signal):
            calls[0] += 1
            trace.append(dict(summary=data))
            if calls[0] == 1:
                mutation = case['mutation']
                if mutation == 'append':
                    session.append('user/message', message('added', 'added'), surface_op='append')
                elif mutation in ('outside', 'rewrite'):
                    seq = 1 if mutation == 'outside' else 0
                    session.append('user/message', message('rewritten', 'rewritten'),
                                   surface_op=dict(op='replace', startSeq=seq, endSeq=seq), source_event_seqs=[seq])
                elif mutation == 'reprice':
                    price[0] += 1
                if extra == 'cancel-summary':
                    controller.abort(RuntimeError('cancelled by caller'))
                if case['retry']:
                    raise RuntimeError('first summary failed')
            return dict(summary=[dict(type='text', text='checkpoint')], provider='test', model='model')
        async def recover(error, agent, selected, signal):
            trace.append(dict(recover=list(selected), message=str(error)))
            if extra == 'cancel-recovery':
                controller.abort(RuntimeError('cancelled by caller'))
            return True
        async def flush():
            trace.append('flush')
            if extra == 'flush':
                raise RuntimeError('disk unavailable')
        engine.summarize, engine.recover_summary = summarize, recover
        row = dict(case=case, trace=trace)
        try:
            result = await compact(engine, session, 0, 0, agent=SimpleNamespace(session=session),
                signal=controller.signal, manual=case['manual'], source_command_id='command', flush=flush)
            row['result'] = {key: value for key, value in result.items() if key != 'compactionId'}
        except Exception as error:
            row['error'] = failure(error)
        row['nodes'] = list(session.surface.nodes)
        row['events'] = [dict(seq=event['seq'], type=event['type'],
            **{key: event[key] for key in ('surfaceOp', 'sourceEventSeqs') if key in event}) for event in session.events]
        row['checkpoints'] = [dict(content=event['data']['content'], source={key: value
            for key, value in event['data']['source'].items() if key != 'compactionId'},
            identity=event['data']['source']['compactionId'] == next(item['data']['compactionId']
                for item in session.events if item['type'] == 'compaction/start'))
            for event in session.events if event['type'] == 'user/message'
            and event['data']['source']['kind'] == 'compact-checkpoint']
        rows.append(row)
        await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


def prepare(output):
    path = output/'cases.json'
    path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_compaction_recovery.mts',
        'Actual format-4 Sessions and region transactions. Selected/whole stability before recovery and commit; '
        'outside append/rewrite, selected replacement/repricing, cancellation, lock, measurement and flush. '
        'Random UUIDs are checked for correlation, event timestamps and error runtime stacks are not compared.',
        [Path(__file__).resolve(), ROOT/'dsh/compaction/transaction.py', ROOT/'dsh/compaction/current.py'], prepare=prepare)
