"""Current-session Auto permission review gate; all effects are owner scoped."""
import asyncio
import json
from pathlib import Path
import weakref

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.fiber import FiberState
from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController, AbortSignal
from dsh.core.cancellation import subscribe_abort
from dsh.core.cleanup import CleanupPromise
from dsh.core.session.json import deep_freeze, UNDEFINED
from dsh.jobs.pump import field
from .auto_review_decision import ask_user, denied, failed, read_decision
from .auto_review_snapshot import snapshot_auto_review, review_messages
from .permission_current import AUTO_PRESET

REVIEW_POLICY = json.loads(Path(__file__).with_name('auto_review_policy.json').read_text(encoding='utf-8'))['policy']


class _ReviewSignal(AbortSignal):
    __slots__ = ('__weakref__',)


def _combined_signal(*sources):
    signal = _ReviewSignal()
    target, detach = weakref.ref(signal), []
    def relay(reason=None):
        current = target()
        if current is not None:
            current._abort(reason)
        for dispose in detach:
            dispose()
    for source in sources:
        dispose = subscribe_abort(source, relay)
        detach.append(dispose)
        if signal.aborted:
            dispose()
            break
    weakref.finalize(signal, lambda: [dispose() for dispose in detach])
    return signal


class CurrentAutoReview(Plugin):
    name = 'experimental-auto-review'
    inject = ['approval', 'llm', 'permissionPresets', 'sessions', 'tools', 'workingDirectory']

    def apply(self, ctx):
        permission = ctx.permissionPresets
        accepting = [True]
        active = set()
        shown_by_session = weakref.WeakKeyDictionary()
        lifecycle = AbortController()

        async def review(execution, next_fn):
            agent = field(execution, 'agent')
            if agent is None or (field(execution, 'parent') is None and field(execution, 'name') == 'run_code'):
                return await await_callback_result(next_fn())
            if permission.current(agent.session) != AUTO_PRESET:
                return await await_callback_result(next_fn())
            if not accepting[0] or lifecycle.signal.aborted:
                return dict(kind='cancel')
            completed = asyncio.get_running_loop().create_future()
            active.add(completed)
            try:
                signal = _combined_signal(field(execution, 'signal'), lifecycle.signal)
                try:
                    shown = shown_by_session.setdefault(agent.session, {})
                    cwd = await ctx.workingDirectory.ensure(agent, signal)
                    snapshot = snapshot_auto_review(agent, execution, cwd, shown)
                    shown[snapshot['pending']['key']] = snapshot['pending']['schema']
                    options = deep_freeze(dict(provider=snapshot['provider'], model=snapshot['model'], system=REVIEW_POLICY,
                        messages=review_messages(snapshot), temperature=0, sessionId=agent.session.id, purpose='auto-review', signal=signal))
                    decision = await read_decision(ctx.llm.stream(options))
                except Exception as error:
                    if lifecycle.signal.aborted:
                        return dict(kind='cancel')
                    return failed(field(execution, 'name'), error)
                if lifecycle.signal.aborted:
                    return dict(kind='cancel')
                reason = decision.get('reason', UNDEFINED)
                if decision['decision'] == 'deny' and ctx.approval.overrideOf(agent.session) == 'never':
                    return denied(field(execution, 'name'), reason)
                downstream = await await_callback_result(next_fn())
                if lifecycle.signal.aborted:
                    return dict(kind='cancel')
                if decision['decision'] == 'allow' or downstream['kind'] != 'allow':
                    return downstream
                return ask_user(field(execution, 'name'), reason)
            finally:
                active.discard(completed)
                if not completed.done():
                    completed.set_result(None)

        def admit():
            if not accepting[0]:
                raise RuntimeError('auto-review: integration is closing')

        def close():
            # Source async functions run this prefix before returning a Promise.
            # Keep admission closed during synchronous migration observers.
            accepting[0] = False
            error = None
            try:
                if ctx.root.fiber.state == FiberState.ACTIVE:
                    for session in ctx.sessions.list():
                        if permission.current(session) == AUTO_PRESET:
                            permission.set(session, 'danger-full-access')
            except BaseException as failure:
                error = failure
            finally:
                lifecycle.abort(RuntimeError('auto-review integration disposed'))
            pending = list(active)
            async def drain():
                await asyncio.gather(*(asyncio.shield(item) for item in pending), return_exceptions=True)
                if error is not None:
                    raise error
            return CleanupPromise(drain())

        def setup():
            yield ctx.on('tools/pre-execute', review, prepend=True)
            yield permission.registerAuto(admit)
            yield close
        ctx.effect(setup, label='auto-review lifecycle')
