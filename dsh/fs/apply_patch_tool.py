"""Current model value, presentation and registration over guarded patch effects."""
import copy
import json
from pathlib import Path

from dsh.llm.error import HarnessError
from .fs_local import FsError
from .patch import parse_patch, PatchParseError
from .patch_executor import execute_patch
from .tool_diff import compute_hunk_diffs, diffs_from_meta

GUIDANCE = ('Prefer apply_patch over separate edit calls for changes across files or separated regions. '
    'Give every hunk enough surrounding context lines to match one place in the current file. '
    'The whole patch is checked first (syntax, hunk matching, missing files) and a rejected patch changes nothing; '
    'once applying starts, operations run in order, stop at the first failure, and are not rolled back, so re-read affected files before retrying when needed.')


class PatchToolError(HarnessError): pass


def rejection(failure):
    return (PatchToolError if failure['code'] in ('PATCH_SYNTAX', 'PATCH_SYMLINK_SOURCE') else FsError)(failure['message'], failure['code'])


def refusal_error(refusals):
    lines = ['- operation '+str(item['operation']['index']+1)+' ('+item['operation']['kind']+' '+item['operation']['path']+', patch line '+str(item['operation']['patchLine'])+'): '+item['failure']['message'] for item in refusals]
    return rejection(dict(code=refusals[0]['failure']['code'], message='Patch rejected before any change ('+str(len(refusals))+' problems):\n'+'\n'.join(lines)))


def patch_tool_value(report):
    if report['phase'] == 'syntax': raise rejection(report['failure'])
    if report['phase'] == 'preflight': raise refusal_error(report['refusals'])
    outcomes = report['outcomes']
    if outcomes and outcomes[0]['status'] == 'failed' and not outcomes[0]['changes'] and all(item['status'] == 'skipped' for item in outcomes[1:]):
        raise refusal_error([outcomes[0]])
    operations = []
    for item in outcomes:
        value = dict(item['operation'], status=item['status'], **item.get('failure', {}))
        if 'changes' in item: value['changes'] = item['changes']
        operations.append(value)
    return dict(phase='commit', cancelled=report['cancelled'], affectedPaths=report['affectedPaths'], operations=operations)


def patch_stopped(value):
    return value['cancelled'] or any(item['status'] != 'completed' for item in value['operations'])


def completed_lines(operations):
    return [dict(add='A', update='M', delete='D')[kind]+' '+item.get('destination', item['path'])
        for kind in ('add', 'update', 'delete') for item in operations
        if item['status'] == 'completed' and ('update' if item['kind'] == 'move' else item['kind']) == kind]


def render_patch(value):
    operations = value['operations']
    if not patch_stopped(value):
        return '\n'.join(['Success. Updated the following files:']+completed_lines(operations)) if operations else 'Success. No operations in patch.'
    completed = sum(item['status'] == 'completed' for item in operations)
    lines = ['Patch stopped after '+str(completed)+' of '+str(len(operations))+' operations.']
    if completed: lines += ['Completed:']+completed_lines(operations)
    for status, title in [('failed', 'Failed:'), ('unknown', 'Outcome unknown:'), ('skipped', 'Not executed:')]:
        selected = [item for item in operations if item['status'] == status]
        if not selected: continue
        lines.append(title)
        for item in selected:
            label = '- operation '+str(item['index']+1)+' ('+item['kind']+' '+item['path']
            if status == 'skipped':
                lines.append(label+')'); continue
            lines.append(label+(' -> '+item['destination'] if 'destination' in item else '')+', patch line '+str(item['patchLine'])+'): '+item['message'])
            if status == 'failed' and item['kind'] == 'move' and item.get('changes'):
                lines.append('  destination '+item['destination']+' was written; source '+item['path']+' remains')
    return '\n'.join(lines)


def patch_presentation_meta(value):
    diffs = []
    for item in value['operations']:
        if item['status'] not in ('completed', 'failed'): continue
        for change in item.get('changes', []):
            if change['before'] is None: continue
            if change['after'] is None: diffs.append(dict(path=change['path'], oldText=change['before'], newText=''))
            else: diffs.extend(compute_hunk_diffs(change['path'], change['before'], change['after']))
    return dict(diffs=[{key:diff[key] for key in ('path', 'oldText', 'newText')} for diff in diffs], stopped=patch_stopped(value))


def present_patch_call(patch):
    try: operations = parse_patch(patch)
    except PatchParseError: return None
    diffs, paths = [], []
    for item in operations:
        path = item['path']
        if item['kind'] == 'add': diffs.append(dict(path=path, oldText=None, newText=item['content']))
        elif item['kind'] == 'update':
            diffs.append(dict(path=path, oldText='\n'.join(line for hunk in item['hunks'] for line in hunk['oldLines']) or None,
                              newText='\n'.join(line for hunk in item['hunks'] for line in hunk['newLines'])))
        paths.append(path)
        if 'moveTo' in item: paths.append(item['moveTo'])
    paths = list(dict.fromkeys(paths))
    return dict(card='diff', title='Apply patch ('+str(len(paths))+(' file)' if len(paths) == 1 else ' files)'), diffs=diffs, locations=[dict(path=path) for path in paths])


def present_patch_result(result):
    if result.get('isError'): return None
    meta = result.get('meta'); diffs = diffs_from_meta(meta)
    if diffs is None: return None
    return dict(card='diff', title='Apply patch (stopped)' if meta.get('stopped') is True else 'Apply patch', diffs=diffs)


def patch_definition(confined):
    with Path(__file__).with_name('patch_tool_current.json').open(encoding='utf-8') as source:
        return json.load(source)['definitions']['confined' if confined else 'local']


def apply_patch_tool(ctx, sandbox):
    def guidance(context): return GUIDANCE if ctx.tools.get('apply_patch', context.get('scope')) is not None else ''
    ctx.systemPrompt.section(dict(name='tool:apply_patch', order=ctx.systemPrompt.getSectionOrder('TOOL_APPLY_PATCH'), text=guidance))
    definition = copy.deepcopy(patch_definition(bool(sandbox.escalation_modes)))
    schema = definition.pop('outputSchema')
    async def execute(arguments, execution):
        policy = await sandbox.resolve_policy('apply_patch', arguments, execution)
        return patch_tool_value(await execute_patch(ctx, sandbox, execution, dict(patch=arguments['input'], sandboxPolicy=policy)))
    definition.update(output=dict(schema=schema, render=lambda _args, value:[dict(type='text', text=render_patch(value))],
                                  presentationMeta=lambda _args, value:patch_presentation_meta(value)),
                      execute=execute, presentCall=lambda args:present_patch_call(args['input']), presentResult=lambda _args, result:present_patch_result(result))
    ctx.tools.register(definition)
