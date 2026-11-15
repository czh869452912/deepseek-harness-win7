"""Current guarded batch patch planning, simulation and sequential publication.

Port of pinned tool-fs/patch; internal reads never establish model observation.
"""
import asyncio

from .fs_local import FsError
from .patch import parse_patch, apply_hunks, PatchParseError
from .tool_fs import _fire_waterfall
from .tool_fs_mutation import remediate_fs_error


async def resolve_options(ctx, execution):
    options = {'signal': execution.signal}
    if getattr(execution, 'agent', None) is not None:
        options['cwd'] = await ctx.workingDirectory.ensure(execution.agent, execution.signal)
    return options


def patch_failure(sandbox, policy, error, path):
    mapped = remediate_fs_error(sandbox.map_error(error, policy), path)
    return dict(code=mapped.code, message=mapped.message)


async def source_intent(ctx, execution, target, kind):
    return await _fire_waterfall(ctx, 'fs/delete-intent' if kind == 'delete' else 'fs/edit-intent', target, execution)


async def destination_intent(ctx, execution, target):
    return await _fire_waterfall(ctx, 'fs/write-intent', target, execution)


async def plan_patch(ctx, sandbox, execution, request):
    parsed = parse_patch(request['patch'])
    targets = {}
    async def resolve(path):
        target = await ctx.fs.resolve(path, await resolve_options(ctx, execution))
        return targets.setdefault(target.targetKey, target)
    result = dict(operations=[], refusals=[])
    for index, operation in enumerate(parsed):
        move = operation.get('moveTo')
        record = dict(index=index, kind='move' if move is not None else operation['kind'],
                      path=operation['path'], patchLine=operation['lineNumber'])
        if move is not None: record['destination'] = move
        failure_path = operation['path']
        try:
            target = await resolve(operation['path'])
            record['path'] = target.displayPath
            planned = dict(target=target, rawPath=operation['path'], record=record, kind=record['kind'])
            if operation['kind'] == 'add': planned['content'] = operation['content']
            if operation['kind'] == 'update':
                planned['hunks'] = operation['hunks']
                if move is not None:
                    failure_path = move
                    planned['destination'] = await resolve(move)
                    record['destination'] = planned['destination'].displayPath
            result['operations'].append(planned)
        except FsError as error:
            result['refusals'].append(dict(operation=record, failure=patch_failure(sandbox, request.get('sandboxPolicy'), error, failure_path)))
    return result


class Preflight:
    def __init__(self, ctx, sandbox, execution, policy):
        self.ctx, self.sandbox, self.execution, self.policy = ctx, sandbox, execution, policy
        self.states = {}
        self.failure_path = ''

    async def state(self, target):
        if target.targetKey not in self.states:
            info = await self.ctx.fs.stat(target, self.execution.signal)
            self.states[target.targetKey] = dict(exists=info is not None, info=info, touched=False)
        return self.states[target.targetKey]

    @staticmethod
    def regular(state, target):
        if state['info'] is not None and state['info'].type != 'file':
            raise FsError('cannot modify "'+target.displayPath+'": not a regular file', 'FS_NOT_REGULAR_FILE')

    async def source(self, state, target, kind):
        intent = None if state['touched'] else await source_intent(self.ctx, self.execution, target, kind)
        if not state['exists']: raise FsError('cannot '+kind+' "'+target.displayPath+'": not found', 'FS_NOT_FOUND')
        self.regular(state, target)
        if intent is not None and intent['version'] != getattr(state['info'], 'version', None):
            raise FsError('cannot '+kind+' "'+target.displayPath+'": file changed since it was read', 'FS_STALE_VERSION')

    async def destination(self, state, target):
        intent = None if state['touched'] else await destination_intent(self.ctx, self.execution, target)
        self.regular(state, target)
        if intent is not None and intent['kind'] == 'createIfAbsent' and state['exists']:
            raise FsError('cannot overwrite existing "'+target.displayPath+'" without reading it first', 'FS_NOT_OBSERVED')
        if intent is not None and intent['kind'] == 'replaceIfVersion' and (not state['exists'] or getattr(state['info'], 'version', None) != intent['version']):
            raise FsError('cannot write "'+target.displayPath+'": file changed since it was read', 'FS_STALE_VERSION')

    async def content(self, state, target):
        if 'content' not in state:
            text = await self.ctx.fs.readText(target, self.execution.signal)
            if '\0' in text: raise FsError('cannot patch "'+target.displayPath+'": binary file', 'FS_NOT_TEXT')
            state['content'] = text.replace('\r\n', '\n')
        return state['content']

    def publish(self, target, content=None):
        state = dict(exists=content is not None, info=None, touched=True)
        if content is not None: state['content'] = content
        self.states[target.targetKey] = state

    async def check(self, operation):
        self.failure_path = operation['target'].displayPath
        try: return await self.simulate(operation)
        except FsError as error: return patch_failure(self.sandbox, self.policy, error, self.failure_path)

    async def simulate(self, operation):
        target, kind = operation['target'], operation['kind']
        if kind == 'move' and target.targetKey == operation['destination'].targetKey:
            raise FsError('cannot move "'+target.displayPath+'" to itself', 'FS_SAME_TARGET')
        if kind in ('delete', 'move'):
            options = await resolve_options(self.ctx, self.execution)
            info = await self.ctx.fs.lstat(operation['rawPath'], options, self.execution.signal)
            if info is not None and info.type == 'symlink':
                return dict(code='PATCH_SYMLINK_SOURCE', message='cannot '+kind+' "'+target.displayPath+'": path is a symbolic link — operate on its target path instead')
        state = await self.state(target)
        if kind == 'add':
            await self.destination(state, target)
            self.publish(target, operation['content'])
        elif kind == 'delete':
            await self.source(state, target, 'delete')
            self.publish(target)
        elif kind in ('update', 'move'):
            await self.source(state, target, 'move' if kind == 'move' else 'edit')
            if kind == 'move':
                self.failure_path = operation['destination'].displayPath
                await self.destination(await self.state(operation['destination']), operation['destination'])
                self.failure_path = target.displayPath
            result = apply_hunks(await self.content(state, target), operation['hunks'])
            if not result['ok']:
                failure = result['failure']; first = ''.join(failure['pattern'][:1])
                preview = first[:80]+'…' if len(first)>80 else first
                return dict(code='FS_PATCH_MISMATCH', hunkLine=failure['hunkLineNumber'], message='cannot patch "'+target.displayPath+'": hunk at patch line '+str(failure['hunkLineNumber'])+' ('+failure['stage']+') does not match — '+preview)
            self.publish(operation['destination'] if kind == 'move' else target, result['after'])
            if kind == 'move': self.publish(target)
        else: raise AssertionError('unexpected planned patch operation')


async def preflight_patch(ctx, sandbox, execution, policy, operations):
    simulation = Preflight(ctx, sandbox, execution, policy)
    refusals = []
    for operation in operations:
        failure = await simulation.check(operation)
        if failure is not None: refusals.append(dict(operation=operation['record'], failure=failure))
    return refusals


async def unchanged(ctx, before):
    try:
        for target, info in before:
            after = await ctx.fs.stat(target)
            if getattr(after, 'version', None) != getattr(info, 'version', None): return False
        return True
    except FsError: return False


async def commit_patch(ctx, sandbox, execution, policy, operations):
    outcomes = [dict(status='skipped', operation=operation['record']) for operation in operations]
    cancelled = False
    for index, operation in enumerate(operations):
        if execution.signal.aborted:
            cancelled = True
            break
        target, kind, record = operation['target'], operation['kind'], operation['record']
        started, before, failure_path = False, [], target.displayPath
        try:
            targets = [operation['destination'], target] if kind == 'move' else [target]
            infos = await asyncio.gather(*(ctx.fs.stat(item, execution.signal) for item in targets))
            before = list(zip(targets, infos))
            if kind == 'move':
                expected_source = await source_intent(ctx, execution, target, 'edit')
                destination = operation['destination']; failure_path = destination.displayPath
                expected_destination = await destination_intent(ctx, execution, destination)
                options = dict(hunks=operation['hunks'])
                if expected_source is not None: options['expectedSource'] = expected_source
                if expected_destination is not None: options['expectedDestination'] = expected_destination
                started = True
                result = await ctx.fs.moveFile(target, destination, options, execution.signal, sandbox_policy=policy)
                changes = [dict(path=ctx.fs.processPath(destination), before=result.destination.before, after=result.destination.after)]
                ctx.emit('fs/observed', destination, dict(kind='present', version=result.destination.version), execution)
                if result.sourceDeleted:
                    ctx.emit('fs/observed', target, dict(kind='absent'), execution)
                    changes.append(dict(path=ctx.fs.processPath(target), before=result.sourceBefore, after=None))
                    outcome = dict(status='completed', operation=record, changes=changes)
                else:
                    error = FsError(result.sourceFailure['message'], result.sourceFailure['code'])
                    outcome = dict(status='failed', operation=record, changes=changes, failure=patch_failure(sandbox, policy, error, target.displayPath))
            else:
                intent = await destination_intent(ctx, execution, target) if kind == 'add' else await source_intent(ctx, execution, target, 'delete' if kind == 'delete' else 'edit')
                started = True
                if kind == 'add': result = await ctx.fs.writeText(target, operation['content'], intent, execution.signal, sandbox_policy=policy)
                elif kind == 'update': result = await ctx.fs.patchText(target, operation['hunks'], intent, execution.signal, sandbox_policy=policy)
                elif kind == 'delete': result = await ctx.fs.deleteFile(target, intent, execution.signal, sandbox_policy=policy)
                else: raise AssertionError('unexpected planned patch operation')
                observation = dict(kind='absent') if kind == 'delete' else dict(kind='present', version=result.version)
                ctx.emit('fs/observed', target, observation, execution)
                changes = [dict(path=ctx.fs.processPath(target), before=result.before, after=None if kind == 'delete' else result.after)]
                outcome = dict(status='completed', operation=record, changes=changes)
        except FsError as error:
            failure = patch_failure(sandbox, policy, error, failure_path)
            uncertain = started and (error.code == 'FS_ABORTED' or (error.code == 'FS_IO_ERROR' and not await unchanged(ctx, before)))
            if uncertain:
                failure['message'] += ' — re-read the affected files before retrying'
                outcome = dict(status='unknown', operation=record, failure=failure)
            else: outcome = dict(status='failed', operation=record, failure=failure, changes=[])
        outcomes[index] = outcome
        if outcome['status'] != 'completed':
            cancelled = execution.signal.aborted
            break
    affected = list(dict.fromkeys(change['path'] for outcome in outcomes for change in outcome.get('changes', [])))
    return dict(phase='commit', outcomes=outcomes, affectedPaths=affected, cancelled=cancelled)


async def execute_patch(ctx, sandbox, execution, request):
    try: plan = await plan_patch(ctx, sandbox, execution, request)
    except PatchParseError as error: return dict(phase='syntax', failure=dict(code='PATCH_SYNTAX', message=error.message))
    policy = request.get('sandboxPolicy')
    refusals = plan['refusals'] + await preflight_patch(ctx, sandbox, execution, policy, plan['operations'])
    refusals.sort(key=lambda refusal: refusal['operation']['index'])
    if refusals: return dict(phase='preflight', refusals=refusals)
    return await commit_patch(ctx, sandbox, execution, policy, plan['operations'])
