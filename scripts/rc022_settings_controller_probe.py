"""Compare current settings Remote callbacks to the unchanged original class."""
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.api.settings_current import CurrentSettingsController
    from dsh.cordis.context import Context
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    ctx = Context(); rows = []; calls = []; opened = []; control = AbortController(); mode = 'ok'
    descriptor = dict(ns='Mixed:entry', autoGenerate=False, schema=dict(type='object'), value=dict(count=2), base=dict(count=1), user=dict(count=2), applies='live', revision=3, secrets=[dict(path=['token'], set=True)], privateField='discard')
    async def prepare():
        if mode == 'cancel': control.abort()
        if mode == 'prepare-fail': raise RuntimeError('preparation failed')
        return 'owned.patch.yml'
    async def update(ns, patch, expected):
        calls.append([ns, patch, expected])
        if mode == 'conflict':
            error = RuntimeError('stale'); error.code = 'SETTINGS_CONFLICT'; error.expected = 1; error.actual = 3
            raise error
        if mode == 'reject': raise RuntimeError('refused')
    async def opener(path, signal):
        if mode == 'open-fail': raise RuntimeError('open failed')
        opened.append(path)
    async def capture(name, callback):
        try:
            value = callback()
            import inspect
            if inspect.isawaitable(value): value = await value
            rows.append(dict(name=name, value=value))
        except Exception as error:
            rows.append(dict(name=name, error=dict(code=error.code, message=error.message, details=error.details)))
    try:
        await ctx.plugin(CurrentSettingsController, dict(openTextFile=opener)); api = ctx.settingsController
        await capture('missing', lambda: api.describe()); await capture('empty', lambda: api.update('', {}, UNDEFINED))
        ctx.set_service('settings', NS(writable=True, describe=lambda _options:[descriptor], prepareDocument=prepare, update=update))
        await capture('describe', lambda: api.describe()); await capture('update', lambda: api.update('Mixed:entry', dict(count=4), UNDEFINED))
        mode = 'conflict'; await capture('conflict', lambda: api.update('Mixed:entry', {}, 1))
        mode = 'reject'; await capture('rejected', lambda: api.update('Mixed:entry', {}, UNDEFINED))
        mode = 'ok'; await capture('open', lambda: api.openSettingsDocument(control.signal))
        mode = 'prepare-fail'; await capture('prepare-fail', lambda: api.openSettingsDocument(control.signal))
        mode = 'open-fail'; await capture('open-fail', lambda: api.openSettingsDocument(control.signal))
        mode = 'cancel'; await capture('cancel-during-prepare', lambda: api.openSettingsDocument(control.signal))
        await capture('already-cancelled', lambda: api.openSettingsDocument(control.signal))
        rows.extend([dict(name='calls', value=calls), dict(name='opened', value=opened)])
        return rows
    finally: await ctx.fiber.dispose()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_settings_controller.mts', 'Original current settings controller and controlled provider callbacks: descriptor projection, non-kebab entry identity, structural conflict, precise refusals, local document preparation/opening and cancellation.', [Path(__file__).resolve(), ROOT/'dsh/api/settings_current.py'])
