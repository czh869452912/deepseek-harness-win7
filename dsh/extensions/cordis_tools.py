"""Model-facing tool-cordis contracts, with a native Python Host half.

Source: pinned extensions/tool-cordis/{index,present,inspect}.ts. Live fibers
remain inside the Host; only the projected diagnostics cross tool boundaries.
"""
import re

from dsh.core.json_schema import _dump
from dsh.extensions.inspect_registry import _throw_if_aborted, _JS_SPACE
from dsh.llm.message import create_user_message


def json_text(value, depth=0):
    """JSON.stringify(value, null, 2) for owned JSON diagnostics."""
    indent, inner = '  ' * depth, '  ' * (depth + 1)
    if isinstance(value, dict):
        if not value:
            return '{}'
        return '{\n' + ',\n'.join(inner + _dump(key) + ': ' + json_text(child, depth + 1)
                                 for key, child in value.items()) + '\n' + indent + '}'
    if isinstance(value, list):
        if not value:
            return '[]'
        return '[\n' + ',\n'.join(inner + json_text(child, depth + 1) for child in value) + '\n' + indent + ']'
    return _dump(value)


def present_call(operation, args):
    kind = 'read'
    if operation == 'inspect_list':
        title = 'List Cordis Inspect Providers'
    elif operation == 'inspect_query':
        title = 'Query Cordis {platform} {provider}.{method}'.format(**args)
    elif operation == 'inspect_self':
        target = args.get('pluginId', 'dynamic Cordis Plugins')
        if 'pluginId' in args and 'packageId' in args:
            target += '/' + args['packageId']
        title = 'Inspect ' + target
    elif operation == 'define':
        target = 'new ' + args['plugin']['idPrefix'] + '-*' if args['plugin']['kind'] == 'new' else args['plugin']['pluginId']
        return dict(card='generic', kind='execute', title='Register Cordis Plugin "{}" for {}: {}'.format(
            args['name'], target, args['purpose']), rawInput=args['code'])
    elif operation == 'run':
        kind = 'execute'
        title = '{} Cordis Plugin {} · {}'.format('Update' if args['mode'] == 'update' else 'Run', args['pluginId'], args['packageId'])
    elif operation == 'stop':
        kind, title = 'execute', 'Stop Cordis Plugin ' + args['pluginId']
    else:
        kind, title = 'delete', 'Remove Cordis Plugin ' + args['pluginId']
    return dict(card='generic', kind=kind, title=title)


def run_meta(_args, value):
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object')
    result = {}
    for key in ('pluginId', 'packageId', 'pluginRunId'):
        if not isinstance(value.get(key), str):
            raise ValueError('expected JSON string field "{}"'.format(key))
        result[key] = value[key]
    return result


def render_result(operation, args, value):
    if operation == 'define':
        text = 'Defined {pluginId}/{packageId} ({name}); it is not running yet. Use cordis_run to activate this Package.'.format(**value)
    elif operation == 'run':
        ids = run_meta(args, value)
        status = {'awaiting-approval': 'awaiting user approval', 'starting': 'starting asynchronously'}.get(value.get('status'), 'running')
        text = '{pluginId}/{packageId} is {} ({pluginRunId}).'.format(status, **ids)
    elif operation == 'stop':
        text = 'Dynamic Plugin {pluginId} is stopped; its definition and versions remain.'.format(**value)
    elif operation == 'undefine':
        text = 'Removed dynamic Plugin {pluginId} and all of its Packages.'.format(**value)
    else:
        text = json_text(value)
    return [dict(type='text', text=text)]


def missing_services(ctx, fiber):
    return [name for name in fiber.inject if ctx.get(name) is None]


def provided_services(ctx, fiber):
    def within(candidate):
        while candidate is not None:
            if candidate is fiber:
                return True
            parent = getattr(candidate, 'parent', None)
            following = getattr(parent, 'fiber', None)
            if following is candidate:
                break
            candidate = following
        return False
    names = [impl.name for impl in ctx.reflect.store.values() if impl is not None and within(impl.fiber)]
    return sorted(names, key=lambda name: name.encode('utf-16-be', errors='surrogatepass'))


def self_state(reference):
    status = reference.get('latestRun', {}).get('status')
    if status == 'awaiting-approval':
        return status
    if status in ('client-pending', 'starting-host'):
        return 'client-pending'
    if status in ('failed', 'rejected', 'cancelled'):
        return 'failed'
    if status in ('waiting', 'running'):
        return status
    if 'activeRun' in reference:
        return 'running'
    return 'stopped' if 'currentPackageId' in reference else 'defined'


def self_summary(reference):
    result = dict(pluginId=reference['pluginId'], name=reference['name'],
                  packageCount=len(reference['packages']) if 'packages' in reference else 1,
                  state=self_state(reference))
    for key in ('currentPackageId', 'nextPackageId'):
        if key in reference:
            result[key] = reference[key]
    if 'activeRun' in reference:
        result['activeRun'] = {key: reference['activeRun'][key] for key in ('pluginRunId', 'packageId')}
    latest = reference.get('latestRun', {})
    if latest.get('status') == 'awaiting-approval':
        result['pendingApproval'] = {key: latest[key] for key in ('pluginRunId', 'packageId', 'mode')}
    return result


def inspect_self_package(ctx, runner, agent, plugin_id, package_id):
    inspected = runner.inspectPackage(agent, plugin_id, package_id)
    row = next((candidate for candidate in runner.snapshot(agent) if candidate['pluginId'] == plugin_id), {})
    package = next((candidate for candidate in row.get('packages', []) if candidate['packageId'] == package_id), {})
    active = row.get('activeRun', {})
    if active.get('packageId') != package_id:
        active = {}
    latest = inspected.get('latestRun', {})
    if latest.get('packageId') != package_id:
        latest = {}
    fiber = active.get('fiber')
    waiting = missing_services(ctx, fiber) if fiber is not None else list(latest.get('host', {}).get('waitingFor', []))
    host_status = 'absent' if package.get('hasHostHalf') is not True else latest.get('host', {}).get('status',
        'stopped' if not active else 'waiting' if waiting else 'running')
    client_status = 'absent' if package.get('hasClientHalf') is not True else latest.get('client', {}).get('status', 'stopped')
    host = dict(status=host_status, provides=[] if fiber is None else provided_services(ctx, fiber),
                waitingFor=waiting, handlers=active.get('handlers', []))
    client = dict(status=client_status, waitingFor=list(latest.get('client', {}).get('waitingFor', [])))
    for name, half in (('host', host), ('client', client)):
        if 'error' in latest.get(name, {}):
            half['error'] = latest[name]['error']
    if 'renderFailure' in active:
        client['renderFailure'] = active['renderFailure']
    return dict(mode='package', plugin=self_summary(inspected), packageId=package_id,
                name=inspected['name'], purpose=inspected['purpose'], code=inspected['code'],
                runtime=dict(state=self_state(inspected), host=host, client=client))


async def execute(ctx, operation, args, execution):
    if operation == 'inspect_list':
        return dict(providers=ctx.get('cordisInspect').list())
    agent = getattr(execution, 'agent', None)
    if agent is None:
        raise ValueError('Cordis dynamic tools require an Agent-backed session')
    runner = ctx.get('dynamicCordisRunner')
    if operation == 'inspect_query':
        from dsh.core.session.json import UNDEFINED
        data = await ctx.get('cordisInspect').query(args['platform'], args['provider'], args['method'],
            args.get('input', UNDEFINED), agent, getattr(execution, 'signal', None))
        return dict(platform=args['platform'], provider=args['provider'], method=args['method'], data=data)
    if operation == 'define':
        return runner.define(dict(args, sessionId=agent.id))
    if operation == 'inspect_self':
        if 'packageId' in args and 'pluginId' not in args:
            raise ValueError('cordis_inspect_self packageId requires pluginId')
        if 'pluginId' not in args:
            return dict(mode='plugins', plugins=[self_summary(reference) for reference in runner.listPlugins(agent)])
        if 'packageId' not in args:
            reference = runner.inspectPlugin(agent, args['pluginId'])
            result = dict(mode='plugin', **self_summary(reference))
            result['packages'] = [dict(package, isCurrent=package['packageId'] == reference.get('currentPackageId'),
                isNext=package['packageId'] == reference.get('nextPackageId')) for package in reference['packages']]
            return result
        return inspect_self_package(ctx, runner, agent, args['pluginId'], args['packageId'])
    receipt = await getattr(runner, operation)(agent, **args, **(dict(signal=getattr(execution, 'signal', None)) if operation == 'run' else {}))
    if not receipt['ok'] and not (operation == 'stop' and receipt.get('reason') == 'not-running'):
        raise ValueError(receipt['message'])
    if operation == 'stop':
        return dict(pluginId=args['pluginId'])
    if operation == 'undefine':
        return dict(pluginId=args['pluginId'], wasRunning=receipt['wasRunning'])
    result = dict(status=receipt['status'], pluginId=args['pluginId'], packageId=args['packageId'], pluginRunId=receipt['pluginRunId'])
    if receipt['status'] != 'running':
        result.update(mode=receipt['mode'], nextPackageId=receipt['nextPackageId'])
        if 'currentPackageId' in receipt:
            result['currentPackageId'] = receipt['currentPackageId']
        return result
    row = next((candidate for candidate in runner.snapshot(agent) if candidate['pluginId'] == args['pluginId']), {})
    active = row.get('activeRun', {})
    fiber = active.get('fiber') if active.get('pluginRunId') == receipt['pluginRunId'] else None
    waiting = missing_services(ctx, fiber) if fiber is not None else []
    result.update(currentPackageId=receipt['currentPackageId'], host=dict(status='absent' if fiber is None else 'waiting' if waiting else 'running',
        provides=[] if fiber is None else provided_services(ctx, fiber), waitingFor=waiting),
        client=dict(status='absent' if 'clientWaitingFor' not in receipt else 'waiting' if receipt['clientWaitingFor'] else 'running',
                    waitingFor=list(receipt.get('clientWaitingFor', []))))
    if 'nextPackageId' in receipt:
        result['nextPackageId'] = receipt['nextPackageId']
    return result


REFERENCE_PATTERN = re.compile(r'(?:^|[' + _JS_SPACE + r'])@([a-z]{3,6}-[0-9]+)(?=[' + _JS_SPACE + r']|$)')


def referenced_plugin_ids(messages):
    found = {}
    for message in messages:
        if message['source']['kind'] != 'user':
            continue
        text = '\n'.join(block['text'] for block in message['content'] if block['type'] == 'text')
        for match in REFERENCE_PATTERN.finditer(text):
            found[match[1]] = None
    return list(found)


def render_reference(reference):
    pid, package_id = reference['pluginId'], reference['packageId']
    mode = 'update' if 'currentPackageId' in reference else 'run'
    return '\n'.join([
        '<cordis_dynamic_plugin_context>', json_text(reference), '',
        'The user explicitly referenced @{}. Use Package {} as the base for this modification.'.format(pid, package_id),
        'Before modifying it, call cordis_inspect_self with pluginId="{}" and packageId="{}" to read the exact metadata and source.'.format(pid, package_id),
        'Use cordis_define with plugin.kind="existing" and the original pluginId="{}" to append an immutable Package.'.format(pid),
        'Do not create a new Plugin for this request. After cordis_define succeeds, call cordis_run mode="{}" with the returned packageId.'.format(mode),
        '</cordis_dynamic_plugin_context>'])


def render_unavailable_reference(pid):
    return '\n'.join([
        '<cordis_dynamic_plugin_context>',
        'The user explicitly referenced @{}, but this Plugin is unavailable in the current Session.'.format(pid),
        'It may have been removed, belong to another Session, or have been lost when the DSH process restarted.',
        'Do not claim that it was updated or silently create a replacement Plugin. Tell the user that the reference is currently unavailable.',
        '</cordis_dynamic_plugin_context>'])


async def pre_step(ctx, payload, next_fn):
    decision = await next_fn()
    if decision['kind'] == 'reject':
        return decision
    ids = referenced_plugin_ids(payload['messages'])
    if not ids:
        return decision
    _throw_if_aborted(payload.get('signal'))
    contexts = []
    for pid in ids:
        reference = ctx.get('dynamicCordisRunner').reference(payload['agent'], pid)
        contexts.append(create_user_message(dict(content=[dict(type='text', text=render_unavailable_reference(pid) if reference is None else render_reference(reference))],
            source=dict(kind='plugin', plugin='tool-cordis', form='instructions'))))
    return dict(decision, messages=list(decision['messages']) + contexts)
