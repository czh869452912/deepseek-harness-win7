"""Pair actual image repair listeners and V4 durable message projection."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return [dict(kind='selection', count=count, reverse=reverse)
            for count in (0, 1, 2, 3, 9, -1, .5) for reverse in (False, True)] + [
        dict(kind='agent', mode=mode) for mode in ('repair', 'other', 'missing', 'aborted')] + [
        dict(kind='summary', mode=mode) for mode in ('repair', 'other', 'foreign', 'missing', 'aborted')] + [
        dict(kind='normalize', value=value) for value in (None, 0, -1, True, .5, '2', 1, 2, 9007199254740991, 9007199254740992)]


def image(name):
    return dict(type='image', attachment=dict(attachmentId='sha256:'+'a'*64,
        name=name, mediaType='image/png', bytes=1, width=1, height=1))


def message(identity, content):
    return dict(id=identity, role='user', source=dict(kind='human'), content=content)


async def observe():
    from dsh.cordis.context import Context
    from dsh.core.runtime_v4 import SessionV4Plugin
    from dsh.core.abort import AbortController
    from dsh.compaction.image_offload_plugin import CurrentImageOffload
    from dsh.compaction.image_offload import offloadOldestImages
    from dsh.llm.llm_service import LlmError
    from dsh.llm.adapter_failure import normalize_llm_failure
    rows = []
    for case in cases():
        if case['kind'] == 'normalize':
            error = LlmError('budget', 'IMAGE_OFFLOAD_REQUIRED', status=413, offloadImages=case['value'])
            rows.append(dict(case=case, result=normalize_llm_failure(error)))
            continue
        ctx = Context()
        ctx.set_service('agents', SimpleNamespace())
        await ctx.plugin(SessionV4Plugin)
        mounted = await ctx.plugin(CurrentImageOffload)
        session = ctx.sessions.prepare('repair')
        detach = ctx.sessions.enter(session)
        ctx.sessions.announce(session)
        try:
            first = session.append('user/message', message('first', [image('first'), image('second')]), surface_op='append')
            last = session.append('user/message', message('last', [image('third')]), surface_op='append')
            selected = [first['seq'], last['seq']]
            controller = AbortController()
            if case['kind'] == 'selection':
                if case['reverse']:
                    selected.reverse()
                result = offloadOldestImages(session, selected, case['count'])
                again = offloadOldestImages(session, selected, 9)
                exhausted = offloadOldestImages(session, selected, 1)
                result = dict(first=result, remainder=again, exhausted=exhausted)
            else:
                mode = case['mode']
                if mode == 'aborted':
                    controller.abort(RuntimeError('controlled abort'))
                failure = dict(message='budget', code='OTHER' if mode == 'other' else 'IMAGE_OFFLOAD_REQUIRED')
                if mode != 'missing':
                    failure['offloadImages'] = 1
                async def fallback():
                    return 'next'
                try:
                    if case['kind'] == 'agent':
                        result = await ctx.waterfall('agent/request-error', dict(agent=SimpleNamespace(session=session),
                            failure=failure, signal=controller.signal), fallback)
                    else:
                        error = LlmError.fromFailure(failure) if mode != 'foreign' else RuntimeError('budget')
                        if mode == 'foreign':
                            error.code, error.failure = failure['code'], failure
                        result = await ctx.waterfall('compaction/summary-error', dict(session=session,
                            sourceEventSeqs=[last['seq']], error=error, signal=controller.signal), fallback)
                except Exception as error:
                    result = dict(error=str(error), same=error is controller.signal.reason)
            decisions = [event['data'] for event in session.snapshotEvents() if event['type'] == 'image/offload']
            names = [block['attachment']['name'] for value in session.deriveMessages() for block in value['content']
                     if block['type'] == 'image' and block.get('offloaded') is True]
            nodes = list(session.surface.nodes)
            await mounted.dispose()
            after = await ctx.waterfall('agent/request-error', dict(), lambda: 'unloaded')
            rows.append(dict(case=case, result=result, decisions=decisions, names=names,
                nodes=nodes, after=after, projections=len(ctx.sessions.messageProjections)))
        finally:
            detach()
            await ctx.fiber.dispose()
    # JSON observations cross the same wire boundary as the original output.
    return json.loads(json.dumps(rows))


def prepare(output):
    path = output/'cases.json'
    path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_image_offload.mts',
        'Actual V4 Sessions, original/native recovery listeners, durable projection, ordered retained image selection, '
        'aborted/foreign failures, unload and validated offload failure snapshots.',
        [Path(__file__).resolve(), ROOT/'dsh/compaction/image_offload.py',
         ROOT/'dsh/compaction/image_offload_plugin.py', ROOT/'dsh/llm/adapter_failure.py',
         ROOT/'dsh/llm/llm_service.py'], prepare=prepare)
