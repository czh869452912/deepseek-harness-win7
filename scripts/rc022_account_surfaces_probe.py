"""Pinned account Host configuration admission, publication and effect ownership."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    values = [None, False, True, '', 0, 1, -1, 1.5, 2147483647, 2147483648, {}, [],
              'welcome', 'credit', 'purpose', 'process', 'done', 'office', 'development', 'both',
              'compact', 'standard', 'detailed', 'completed', 'skipped', 'api-key',
              'https://form.test/path', 'https://form.test', 'http://form.test/path',
              'https://form.test/\nignored', 'https://form.test/path\nignored']
    fields = ['contactFormUrl', 'contactSource', 'version', 'step', 'purpose', 'process',
              'completion', 'usage', 'developerTools']
    rows = [dict(kind='account', mode='initial', config={}), dict(kind='notification', mode='initial', config={})]
    rows += [dict(kind='account', mode='initial', config={field: value}) for field in fields for value in values]
    rows += [dict(kind='notification', mode='initial', config=dict(notificationPollIntervalMs=value)) for value in values]
    rows += [dict(kind='account', mode=mode, config=dict(step='credit', purpose='office', process=None,
        contactSource='public-source', unusedSecret='not-public')) for mode in ['initial', 'late', 'absent']]
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.json_text import stringify_json
    from dsh.client.account_surfaces_current import CurrentUiSettingsAccount, CurrentUiAccountNotifications
    from dsh.settings.schema_current import plain_config
    from dsh.cordis.utils import _UNDEFINED
    def json_value(value):
        if isinstance(value, dict): return {key: json_value(item) for key, item in value.items() if item is not _UNDEFINED}
        if isinstance(value, list): return [None if item is _UNDEFINED else json_value(item) for item in value]
        return value
    rows = []
    for case in cases():
        ctx = Context(); calls = []; disposed = []; fiber = None
        def configure(policy, owner):
            calls.append(dict(policy=policy, owned=owner is fiber))
            return lambda: disposed.append(True)
        settings = SimpleNamespace(configure=configure)
        if case['mode'] == 'initial': ctx.set_service('settings', settings)
        try:
            try:
                fiber = ctx.plugin(CurrentUiSettingsAccount if case['kind'] == 'account' else CurrentUiAccountNotifications, case['config'])
                await fiber
            except Exception:
                rows.append(dict(accepted=False)); continue
            if case['mode'] == 'late':
                ctx.set_service('settings', settings)
                for _ in range(3): await asyncio.sleep(0)
            table = []; ctx.emit('webserver/index-inject', table, dict(principal=dict(kind='owner')))
            row = json.loads(stringify_json(json_value(dict(accepted=True, config=plain_config(fiber.effectiveConfig), table=table))))
            # owner is captured by the real Fiber even during synchronous apply.
            row['calls'] = [dict(policy=call['policy']) for call in calls]
            await fiber.dispose()
            after = []; ctx.emit('webserver/index-inject', after)
            row.update(disposed=len(disposed), after=after)
            rows.append(row)
        finally: await ctx.fiber.dispose()
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_account_surfaces.mts',
        'Actual account settings/notification Host halves: schema acceptance/defaults, volatile projection, public index bootstrap, initial/late/absent settings and reversible presentation effects.',
        [Path(__file__).resolve(), ROOT/'dsh/client/account_surfaces_current.py'], prepare=prepare)
