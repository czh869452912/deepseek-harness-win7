"""Pair catalog-only discovery and path lookup, including scoped release."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.subagent.list_children import list_children, list_descendants, resolve_agent_path
    from dsh.subagent.errors import SubagentError
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    rows = []
    for action in ('walk', 'direct', 'path', 'external-path', 'invalid-path', 'historical-id', 'root-error', 'branch-corrupt',
                   'branch-unavailable', 'root-projection', 'branch-projection', 'missing-query', 'missing-store',
                   'abort-before', 'abort-root', 'abort-branch', 'subagent-error'):
        def entry(identity, mode='continuable', name=None):
            return dict(id=identity, createdAt=1, mode=mode, **(dict(label=identity) if mode == 'continuable' else {}),
                        **(dict(name=name) if name is not None else {}))
        graph = dict(root=[entry('a',name='alpha'), entry('ext','external','external'), entry('old','unknown'),entry('a',name='duplicate')],
                     a=[entry('nested',name='nested'),entry('root',name='cycle')], nested=[],
                     old=[entry('legacy-nested', name='leaf')], **{'legacy-nested':[]})
        controller = AbortController()
        trace, active, peak = [], 0, 0
        primary = RuntimeError('read failed')
        primary.code = 'SESSION_QUERY_CORRUPT_SESSION' if action == 'branch-corrupt' else 'IO_FAILED'
        if action == 'subagent-error': primary = SubagentError('domain failure', 'DOMAIN_FAILURE')
        async def observe_session(identity, options):
            nonlocal active, peak
            assert active == 0, 'observation leaked into the next read'
            trace.append('read:'+identity)
            await asyncio.sleep(0)
            if action == 'root-error' and identity == 'root' or action in ('branch-corrupt','branch-unavailable','subagent-error') and identity == 'a':
                raise primary
            active += 1; peak = max(peak, active)
            if action == 'abort-root' and identity == 'root' or action == 'abort-branch' and identity == 'a': controller.abort()
            def dispose():
                nonlocal active
                active -= 1; trace.append('dispose:'+identity)
            projections = dict(values=dict(subagentCatalog=graph[identity]))
            if action == 'root-projection' and identity == 'root' or action == 'branch-projection' and identity == 'a': projections = dict(values={})
            return SimpleNamespace(projections=projections, dispose=dispose)
        services = dict(sessionQuery=SimpleNamespace(observeSession=observe_session),
                        sessions=SimpleNamespace(get=lambda identity: object() if identity == 'a' else None))
        if action == 'missing-query': services.pop('sessionQuery')
        if action == 'missing-store': services.pop('sessions')
        if action == 'abort-before': controller.abort()
        ctx = SimpleNamespace(get=lambda name: services.get(name))
        row = dict(action=action)
        try:
            if action == 'direct':
                value = await list_children(ctx, 'root', controller.signal)
                row['same'] = value is graph['root']
            elif action in ('path', 'external-path', 'invalid-path', 'historical-id'):
                name = dict(path='alpha/nested', **{'external-path':'external/child','invalid-path':'lead/alpha','historical-id':'legacy-id'})[action]
                value = await resolve_agent_path(ctx, 'root', name, controller.signal)
                if value is UNDEFINED: value = None
            else: value = await list_descendants(ctx, 'root', controller.signal)
            row['value'] = value
        except Exception as error:
            row['error'] = dict(code=getattr(error, 'code', None), same=error is primary)
        row.update(trace=trace, active=active, peak=peak)
        rows.append(row)
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_catalog_walk.mts', 'Catalog-only stable preorder and first-visit paths, external leaves and unknown-mode descendants, scoped observation release, root/branch failures, cancellation and selective name-path reads.',
        [Path(__file__).resolve(), ROOT/'dsh/subagent/list_children.py'])
