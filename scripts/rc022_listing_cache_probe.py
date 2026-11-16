"""Pair credential/generation-scoped model-listing cache transitions."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

OPS = [
    ['token', None], ['view', 'signed-out'], ['await', 'signed-out'], ['snapshot', 'unauthenticated'],
    ['token', 'a'], ['view', 'first', True], ['view', 'shared'], ['snapshot', 'shared-load'],
    ['abort', 'first'], ['await', 'first'], ['snapshot', 'abandoned'], ['resolve', 0, 'a'], ['await', 'shared'], ['snapshot', 'first-success'],
    ['advance'], ['view', 'stale'], ['await', 'stale'], ['reject', 1], ['snapshot', 'retained'],
    ['advance'], ['view', 'stale2'], ['await', 'stale2'], ['reject', 2], ['snapshot', 'one-warning'],
    ['advance'], ['view', 'same'], ['await', 'same'], ['resolve', 3, 'a'], ['snapshot', 'no-change-notification'],
    ['advance'], ['view', 'badge'], ['await', 'badge'], ['resolve', 4, 'a', 'new'], ['snapshot', 'badge-change'],
    ['token', 'b'], ['view', 'old-generation'], ['snapshot', 'rescope'], ['invalidate'], ['view', 'new-generation'],
    ['resolve', 5, 'old'], ['await', 'old-generation'], ['snapshot', 'late-old-ignored'],
    ['resolve', 6, 'b'], ['await', 'new-generation'], ['snapshot', 'new-generation-committed'],
    ['credential-error', True], ['refresh'], ['refresh'], ['snapshot', 'credential-failure-streak'],
    ['credential-error', False], ['token', None], ['refresh'], ['snapshot', 'signed-out-automatic'],
    ['token', 'c'], ['view', 'c'], ['resolve', 7, 'c'], ['await', 'c'], ['settings-off'], ['refresh'], ['snapshot', 'disabled'],
    ['settings-on'], ['view', 'disposing'], ['dispose-start'], ['snapshot', 'dispose-waits'],
    ['resolve', 8, 'late'], ['await', 'disposing'], ['dispose-await'], ['view', 'closed'], ['await', 'closed'], ['snapshot', 'closed'],
]


def prepare(output):
    path = output/'input.json'
    path.write_text(json.dumps(OPS), encoding='utf-8')
    return [path]


def listing(identity, badge=None):
    entry = dict(id=identity, requirement=dict(kind='none'), capabilities=dict(usable=True, facts=dict(inputModalities=['text'])))
    if badge is not None:
        entry['badge'] = dict(kind='badge', badge=dict(text=badge, tone='info'))
    return dict(entries=[entry], skipped=0)


async def observe():
    from dsh.core.abort import AbortController
    from dsh.llm.model_listing_cache import ModelListingCache
    state = dict(token='a', now=0, credentialError=False, settings=True)
    settings = dict(url='https://api.example/models', timeoutMs=10000, maxAgeMs=1000000)
    loads, info, warn, changed, views, controllers, outcomes, snapshots = [], [], [], [], {}, {}, {}, []
    def credential(url):
        if state['credentialError']: raise RuntimeError('credential lookup')
        return state['token']
    def load(url, token, signal):
        future = asyncio.get_running_loop().create_future()
        loads.append(dict(url=url, token=token, signal=signal, future=future))
        return future
    cache = ModelListingCache(dict(settings=lambda: settings if state['settings'] else None, credential=credential, load=load,
        now=lambda: state['now'], info=info.append, warn=warn.append, changed=lambda: changed.append(True)))
    async def flush():
        for _ in range(12): await asyncio.sleep(0)
    disposing = None
    try:
        for op in OPS:
            kind = op[0]
            if kind == 'token': state['token'] = op[1]
            elif kind == 'advance': state['now'] += 1000000
            elif kind == 'credential-error': state['credentialError'] = op[1]
            elif kind == 'settings-off': state['settings'] = False
            elif kind == 'settings-on': state['settings'] = True
            elif kind == 'view':
                controller = controllers[op[1]] = AbortController()
                views[op[1]] = asyncio.create_task(cache.view(settings, controller.signal if len(op) > 2 else None))
            elif kind == 'await':
                try: outcomes[op[1]] = await views[op[1]]
                except Exception as error: outcomes[op[1]] = dict(error=str(error))
            elif kind == 'abort': controllers[op[1]].abort(RuntimeError('caller left'))
            elif kind == 'resolve': loads[op[1]]['future'].set_result(listing(op[2], op[3] if len(op) > 3 else None))
            elif kind == 'reject': loads[op[1]]['future'].set_exception(RuntimeError('offline'))
            elif kind == 'invalidate': cache.invalidate()
            elif kind == 'refresh': await cache.refresh(settings)
            elif kind == 'dispose-start': disposing = asyncio.create_task(cache.dispose())
            elif kind == 'dispose-await': await disposing
            elif kind == 'snapshot':
                snapshots.append(dict(name=op[1], current=cache.current(), loads=[dict(url=row['url'], token=row['token'], aborted=row['signal'].aborted) for row in loads],
                    info=list(info), warn=list(warn), changed=len(changed), outcomes=dict(outcomes), disposalDone=disposing is not None and disposing.done()))
            await flush()
        return snapshots
    finally:
        for row in loads:
            if not row['future'].done(): row['future'].set_result(listing('cleanup'))
        await cache.dispose()
        await asyncio.gather(*views.values(), return_exceptions=True)


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_listing_cache.mts', 'Original/native credential-scoped model cache: single flight and caller-only abandonment, '
        'stale refresh and last-good retention, warning streaks, exact badge change notification, invalidation/credential generations, '
        'signed-out/disabled listing and disposal awaiting late loads. Internal absent listing uses explicit null at the observation boundary.',
        [Path(__file__).resolve(), ROOT/'dsh/llm/model_listing_cache.py'], prepare=prepare)
