"""Pair the original agent management tool, approval seams and result guidance."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

DATA = json.loads((ROOT/'dsh/resources/plugin_manager_tools_022.json').read_text(encoding='utf-8'))


def cases():
    rows = [dict(name='plugins-page', args=dict(action='list_plugins', offset=1, limit=1)),
            dict(name='bundles', args=dict(action='list_bundles')),
            dict(name='empty-page', args=dict(action='list_plugins', offset=99)),
            dict(name='exemptions', args=dict(action='list_version_exemptions')),
            dict(name='exemptions-spread', args=dict(action='list_version_exemptions'), overrideVersion=True)]
    for key, value in [('offset', -1), ('offset', .5), ('limit', 0), ('limit', 101), ('limit', 1.5)]:
        rows.append(dict(name='bad-page-'+key+'-'+str(value), args=dict(action='list_plugins', **{key: value})))
    for action in ['set_plugin', 'set_bundle', 'install_bundle', 'remove_bundle', 'set_version_exemption']:
        rows.append(dict(name='missing-'+action, args=dict(action=action)))
        args = dict(action=action, target='@fixture/plugin@1.0.0')
        if action in ('set_plugin', 'set_bundle'): args['enabled'] = False
        elif action == 'install_bundle': args.update(enabled=False, registry='https://registry.example', approvedBuilds=['build-one'])
        elif action == 'set_version_exemption': args.update(enabled=True, runtimeVersion='0.2.2-rc.3', acceptRisk=True)
        rows.append(dict(name='apply-'+action, args=args))
    for application in ['cancelled', 'overridden', 'restart-required']:
        rows.append(dict(name=application, args=dict(action='set_plugin', target='entry', enabled=True), result=dict(application=application)))
    for reason in DATA['RESTART_STEPS']:
        rows.append(dict(name='restart-'+reason, args=dict(action='set_plugin', target='entry', enabled=True), result=dict(application='restart-required', restartReason=reason)))
    for code in DATA['ERROR_STEPS']:
        rows.append(dict(name='error-'+code, args=dict(action='set_plugin', target='entry', enabled=True), result=dict(application='failed', error=dict(code=code), packageResult=dict(kind='network'))))
    for kind in DATA['FAILURE_STEPS']:
        rows.append(dict(name='failure-'+kind, args=dict(action='install_bundle', target='fixture'), result=dict(application='failed', packageResult=dict(kind=kind))))
    for outcome in ['allowed-once', 'rejected', 'cancelled', 'unavailable']:
        rows.append(dict(name='approval-'+outcome, args=dict(action='list_plugins'), mode='read-only', approval=outcome))
    rows.extend([dict(name='approval-missing', args=dict(action='list_plugins'), mode='workspace-write', noApproval=True),
                 dict(name='agent-missing', args=dict(action='list_plugins'), mode='read-only', noAgent=True),
                 dict(name='aborted', args=dict(action='list_plugins'), aborted=True)])
    return rows


def prepare(output):
    path = output/'input.json'
    path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


async def observe():
    from dsh.boot.plugin_manager_tools import CurrentPluginManagerTools
    from dsh.boot.plugin_compatibility import get_dsh_runtime_version
    from dsh.core.abort import AbortController
    rows = []
    for test in cases():
        calls, captured = [], []
        controller = AbortController()
        policy = dict(mode=test.get('mode', 'danger-full-access'))
        class Manager:
            def listVersionExemptions(self):
                calls.append(dict(op='listVersionExemptions', args=[]))
                return dict(exemptions=[], warnings=[], **(dict(runtimeVersion='manager-override') if test.get('overrideVersion') else {}))
        manager = Manager()
        for method in ['listPlugins', 'listBundles', 'setPluginEnabled', 'setBundleEnabled', 'installBundle', 'removeBundle', 'setVersionExemption']:
            async def invoke(*args, method=method):
                calls.append(dict(op=method, args=list(args)))
                if method.startswith('list'):
                    return [dict(entryId='first', meta=dict(private=True)), dict(name='bundle', rows=[dict(id='row', meta=dict(secret=True))],
                        meta=dict(private=True), update=dict(available=True), listedByDefault=True), dict(entryId='last')]
                return test.get('result', dict(application='applied'))
            setattr(manager, method, invoke)
        async def approve(request):
            calls.append(dict(op='approval', **{key: request[key] for key in ('toolName', 'callId', 'reason', 'displayReason')}))
            return test.get('approval', 'allowed-once')
        approval = None if test.get('noApproval') else NS(request=approve)
        def resolve(options):
            calls.append(dict(op='policy', hasSession='session' in options)); return policy
        ctx = NS(tools=NS(register=captured.append), sandboxPolicy=NS(resolve=resolve), pluginManager=manager, get=lambda name: approval)
        plugin = CurrentPluginManagerTools()
        plugin.apply(ctx)
        definition = captured[0]
        if test.get('aborted'): controller.abort(ValueError('cancelled'))
        execution = NS(agent=None if test.get('noAgent') else NS(session=object()), callId='call', signal=controller.signal)
        try:
            value = await definition['execute'](test['args'], execution)
            result = json.loads(value)
            if test['name'] == 'exemptions':
                assert result['runtimeVersion'] == get_dsh_runtime_version()
                result['runtimeVersion'] = '<active-runtime>'
            outcome = dict(value=result)
        except Exception as error:
            outcome = dict(error=getattr(error, 'message', str(error)))
        rows.append(dict(name=test['name'], outcome=outcome, calls=calls, mode=policy['mode'],
            view=definition['presentCall'](test['args']), listeners=len(controller.signal._listeners)))
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_plugin_tools.mts', 'Original/native plugin_manager: Source schema, per-call full-access escalation, pagination/private metadata projection, '
        'all eight actions, persistent option forwarding, change/error/restart/package guidance and call presentation. Runtime-version identity remains each installation own active version.',
        [Path(__file__).resolve(), ROOT/'dsh/boot/plugin_manager_tools.py', ROOT/'dsh/resources/plugin_manager_tools_022.json'], prepare=prepare)
