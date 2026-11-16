"""Agent-scoped, call-approved access to the current profile manager."""
import json
import math
from pathlib import Path

from dsh.boot.plugin_compatibility import get_dsh_runtime_version
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.sandbox.escalation_current import approve_escalation
from dsh.typert.stores import field

_DATA = json.loads((Path(__file__).resolve().parents[1]/'resources'/'plugin_manager_tools_022.json').read_text(encoding='utf-8'))


def with_next_step(result):
    application = result['application']
    if application == 'applied':
        return result
    if application == 'cancelled':
        step = 'The installation was cancelled and its files restored; nothing changed.'
    elif application == 'overridden':
        step = 'Saved, but a higher-priority layer such as the agent preset overrides it; tell the user it is not in effect.'
    elif application == 'restart-required':
        reason = '' if 'restartReason' not in result else ': '+_DATA['RESTART_STEPS'].get(result['restartReason'], 'undefined')
        step = 'Tell the user to restart DSH to apply this change'+reason+'.'
    elif application == 'failed':
        code = (result.get('error') or {}).get('code') or 'operation-error'
        kind = (result.get('packageResult') or {}).get('kind') if code == 'operation-error' else None
        step = _DATA['FAILURE_STEPS'].get(kind, _DATA['ERROR_STEPS'].get(code))
    else:
        raise RuntimeError('unreachable ChangeResult.application: '+str(application))
    return dict(result, nextStep=step) if step is not None else dict(result)


class CurrentPluginManagerTools(Plugin):
    id = '@deepseek-ai/dsh-plugin-manager/tools'
    inject = ['tools', 'pluginManager', 'sandboxPolicy']

    def apply(self, ctx):
        async def execute(args, execution):
            agent = field(execution, 'agent')
            policy = ctx.sandboxPolicy.resolve({} if agent is None else dict(session=agent.session))
            await approve_escalation(dict(requestedMode='danger-full-access', effectiveMode=field(policy, 'mode'),
                subject='plugin management operation', justification='plugin_manager '+stringify_json(args)
                    +'. Profile changes persist across sessions; installed Host code runs outside the workspace sandbox.'),
                dict(approver=ctx.get('approval'), agent=agent, callId=execution.callId,
                     toolName='plugin_manager', signal=execution.signal))
            execution.signal.throwIfAborted()
            manager, action = ctx.pluginManager, args['action']
            if action == 'list_version_exemptions':
                result = dict(runtimeVersion=get_dsh_runtime_version())
                result.update(manager.listVersionExemptions())
                return stringify_json(result)
            if action == 'set_version_exemption':
                if any(key not in args for key in ('target', 'runtimeVersion', 'enabled')):
                    raise RuntimeError('target package-name@version, runtimeVersion, and enabled are required')
                result = await await_callback_result(manager.setVersionExemption(args['target'], args['runtimeVersion'], args['enabled'], args.get('acceptRisk')))
            elif action in ('list_plugins', 'list_bundles'):
                offset, limit = args.get('offset', 0), args.get('limit', 25)
                def integer(value):
                    return type(value) in (int, float) and math.isfinite(value) and int(value) == value
                if not integer(offset) or offset < 0 or not integer(limit) or limit < 1 or limit > 100:
                    raise RuntimeError('offset must be a non-negative integer and limit must be an integer from 1 to 100')
                rows = await await_callback_result(manager.listPlugins() if action == 'list_plugins' else manager.listBundles())
                entries = []
                for row in rows[int(offset):int(offset+limit)]:
                    item = {key: value for key, value in row.items() if key != 'meta'}
                    if 'rows' in item:
                        item.pop('update', None)
                        item.pop('listedByDefault', None)
                        item['rows'] = [{key: value for key, value in declared.items() if key != 'meta'} for declared in item['rows']]
                    entries.append(item)
                return stringify_json(dict(entries=entries, total=len(rows), nextOffset=offset+len(entries) if offset+len(entries) < len(rows) else None))
            elif action in ('set_plugin', 'set_bundle'):
                if any(key not in args for key in ('target', 'enabled')):
                    raise RuntimeError('target and enabled are required')
                method = manager.setPluginEnabled if action == 'set_plugin' else manager.setBundleEnabled
                result = await await_callback_result(method(args['target'], args['enabled']))
            elif action == 'install_bundle':
                if 'target' not in args:
                    raise RuntimeError('target package spec is required')
                result = await await_callback_result(manager.installBundle(args['target'],
                    {key: args[key] for key in ('enabled', 'approvedBuilds', 'registry') if key in args}))
            elif action == 'remove_bundle':
                if 'target' not in args:
                    raise RuntimeError('target bundle name is required')
                result = await await_callback_result(manager.removeBundle(args['target']))
            else:
                raise RuntimeError('unreachable plugin management action: '+str(action))
            return stringify_json(with_next_step(result))

        ctx.tools.register(dict(name=_DATA['name'], description=_DATA['description'], parameters=_DATA['parameters'],
            execute=execute, output=dict(schema=_DATA['output']['schema'], render=lambda args, value: [dict(type='text', text=value)]),
            presentCall=lambda args: dict(card='generic', title='Manage profile plugins',
                kind='read' if args['action'].startswith('list_') else 'other', rawInput=args)))
