"""Candidate instruction projection at tool ancestry and durable step boundaries."""
import asyncio
from weakref import WeakKeyDictionary

from dsh.cordis.plugin import Plugin
from dsh.cordis.utils import deep_equal
from dsh.core.abort import AbortController
from dsh.llm.message import create_user_message
from .config_authorized import resolve_config, workspace_baseline_identity, JS_WHITESPACE
from .files_authorized import find_project_root, load_baseline_instruction_set, trimmed_digest, field
from .render_authorized import disabled
from .scope_authorized import instruction_candidate_group, instruction_scope_key, scope_for_display_path
from .state_authorized import (agent_instructions_message, baseline_instruction_state,
    reconcile_instruction_context, apply_instruction_version_updates)


def is_instruction_message(message):
    return field(field(message, 'source', {}), 'kind') == 'agent-instructions'


def same_context_payload(left, right):
    return deep_equal(field(left, 'content'), field(right, 'content'), True) and deep_equal(field(left, 'source'), field(right, 'source'), True)


def visible_baseline_source(agent, authority):
    for message in reversed(authority):
        source = field(message, 'source', {})
        if source.get('kind') == 'agent-instructions' and source.get('baseline') is True:return source
    for seq in reversed(agent.session.surface.nodes):
        event = agent.session.eventAt(seq)
        if event is None or event['type'] != 'user/message':continue
        source = event['data']['source']
        if source.get('kind') == 'agent-instructions' and source.get('baseline') is True:return source
    return None


class AuthorizedInstructionRuntime:
    def __init__(self, ctx, config):
        self.ctx, self.resolved = ctx, resolve_config(config)
        self.versions, self.preparations = WeakKeyDictionary(), WeakKeyDictionary()
        self.lifecycle = AbortController();self.executions = {}
        self.tails, self.step_touches = WeakKeyDictionary(), WeakKeyDictionary()
        ctx.effect(lambda:self.dispose, 'agent-instructions.projectionLifecycle')
        ctx.on('session/event', self.session_event)
        ctx.on('agent/pre-step', self.pre_step)
        ctx.on('tools/result', self.tool_result)

    def dispose(self):
        self.lifecycle.abort(RuntimeError('agent-instructions disposed'));self.executions.clear()

    async def compose(self, agent, signal, claimed, pending, touched_paths=()):
        signal.throwIfAborted();resolved = self.resolved
        if disabled(resolved['maxBytes']):return None
        filesystem = self.ctx.get('fs')
        if filesystem is None:return None
        content, changes, desired_baseline, authority = [], [], False, list(claimed)
        cwd = await self.ctx.get('workingDirectory').ensure(agent, signal)
        root = await find_project_root(cwd, resolved['projectRootMarkers'], filesystem, signal)
        identity = workspace_baseline_identity(resolved, cwd, root)
        prepared = self.preparations.get(agent.session)
        if not touched_paths and pending and prepared is not None and prepared['identity'] == identity:return pending[0]
        visible = visible_baseline_source(agent, authority)
        present = visible is not None;keep = present and visible.get('baselineIdentity') == identity
        excluded = prepared['excludedScopes'] if keep and prepared is not None and prepared['identity'] == identity else None
        next_preparation = None
        if not present or not keep or excluded is None:
            replace = present and not keep
            instructions = await load_baseline_instruction_set(dict(resolved, cwd=cwd, projectRoot=root,
                replacePreviousBaseline=replace, signal=signal), filesystem)
            included = instructions['included'] if instructions is not None else []
            baseline = baseline_instruction_state(included)
            observed = baseline_instruction_state(instructions['observed'] if instructions is not None else [])
            included_digests = {}
            for file in included:
                group = instruction_candidate_group(scope_for_display_path(file['displayPath']))
                included_digests.setdefault(group, set()).add(trimmed_digest(file['content']))
            excluded = set(observed['changes']) - set(baseline['changes'])
            for file in instructions['deduped'] if instructions is not None else ():
                group = instruction_candidate_group(scope_for_display_path(file['displayPath']))
                if trimmed_digest(file['content']) in included_digests.get(group, ()):
                    excluded.discard(instruction_scope_key(file['displayPath']))
            next_preparation = dict(identity=identity, excludedScopes=excluded)
            if baseline['versions']:self.versions.setdefault(agent.session, {}).update(baseline['versions'])
            if not keep and instructions is not None and instructions['rendered']['text']:
                baseline_content = agent_instructions_message(instructions['rendered']['text'])['content']
                content.extend(baseline_content)
                replacement_scopes = set(baseline['changes'])
                removals = [dict(action='remove', scope=change['scope'], path=change['path'])
                    for change in visible['changes'] if change['action'] != 'remove' and change['scope'] not in replacement_scopes] if replace else []
                baseline_changes = removals + list(baseline['changes'].values());changes.extend(baseline_changes)
                authority.append(create_user_message(dict(content=baseline_content, source=dict(kind='agent-instructions',
                    form='instructions', baseline=True, baselineIdentity=identity, changes=baseline_changes))))
                desired_baseline = True
        options = dict(cwd=cwd,authorityMessages=authority,scopeMessages=pending,includeBaselineScopes=keep,
            touchedPaths=touched_paths,projectRoot=root,signal=signal)
        if keep:options['excludedBaselineScopes'] = excluded
        update = await reconcile_instruction_context(agent, resolved, self.versions, filesystem, options)
        if update is not None:
            content.extend(update['context']['content']);changes.extend(update['context']['source']['changes'])
            apply_instruction_version_updates(agent.session, update['versionUpdates'], self.versions)
        if next_preparation is not None:self.preparations[agent.session] = next_preparation
        if not content:return None
        source = dict(kind='agent-instructions', form='instructions', changes=changes)
        if desired_baseline:source.update(baseline=True, baselineIdentity=identity)
        return create_user_message(dict(content=content, source=source))

    def sync_inbox(self, agent, claimed, desired):
        pending = [message for message in agent.inbox.nextStep if is_instruction_message(message)]
        already = desired is not None and (any(same_context_payload(message, desired) for message in claimed) or any(
            event is not None and event['type'] == 'user/message' and same_context_payload(event['data'], desired)
            for event in (agent.session.eventAt(seq) for seq in agent.session.surface.nodes)))
        if desired is None or already:
            for message in pending:agent.inbox.remove(message['id'])
            return
        reusable = next((message for message in pending if same_context_payload(message, desired)), None)
        if reusable is not None:
            for message in pending:
                if message is not reusable:agent.inbox.remove(message['id'])
            return
        if not pending:agent.inbox.prepend('next-step', desired)
        else:agent.inbox.replace(pending[0]['id'], desired)
        for message in pending[1:]:agent.inbox.remove(message['id'])

    async def compose_and_sync(self, agent, signal, claimed, touched_paths=()):
        pending = [message for message in agent.inbox.nextStep if is_instruction_message(message)]
        desired = await self.compose(agent, signal, claimed, pending, touched_paths)
        signal.throwIfAborted();self.sync_inbox(agent, claimed, desired)

    def queue_projection(self, agent, path):
        previous = self.tails.get(agent)
        async def project():
            try:
                if previous is not None:await asyncio.shield(previous)
                await self.compose_and_sync(agent, self.lifecycle.signal, [], [path])
            except Exception as error:
                if not self.lifecycle.signal.aborted:self.ctx.logger.warn('workspace instruction refresh failed: %o', error)
        current = asyncio.ensure_future(project());self.tails[agent] = current
        def settled(task):
            if self.tails.get(agent) is task:self.tails.pop(agent, None)
        current.add_done_callback(settled)

    async def wait_for_projections(self, agent):
        while agent in self.tails:
            current = self.tails[agent];await asyncio.shield(current)
            # Promise continuation removes the exact tail before another loop turn.
            if self.tails.get(agent) is current and current.done():self.tails.pop(agent, None)

    def project_touch(self, agent, path):
        boundary = self.ctx.get('agents').turnBoundaryOf(agent.session)
        step = boundary['lastStepBoundary']
        if boundary['openTurnStartSeq'] is not None and step is not None and step['kind'] == 'start' and step['seq'] > boundary['openTurnStartSeq']:
            self.step_touches.setdefault(agent.session, []).append((agent, path))
        else:self.queue_projection(agent, path)

    def session_event(self, session, event):
        if event['type'] != 'step/end':return
        for agent, path in self.step_touches.pop(session, []):self.queue_projection(agent, path)

    async def pre_step(self, payload, next_fn):
        decision = await next_fn();agent = payload['agent'];claimed = payload['messages'];signal = payload['signal']
        await self.wait_for_projections(agent)
        pending = [message for message in agent.inbox.nextStep if is_instruction_message(message)]
        desired = await self.compose(agent, signal, claimed, pending);signal.throwIfAborted()
        if decision['kind'] == 'reject' or payload['step'] == 1 and not decision['messages']:
            self.sync_inbox(agent, claimed, desired);return decision
        for message in pending:agent.inbox.remove(message['id'])
        if desired is None or any(same_context_payload(message, desired) for message in decision['messages']):return decision
        position = max((index for index, message in enumerate(decision['messages']) if any(message is item for item in claimed)), default=-1) + 1
        messages = list(decision['messages']);messages.insert(position, desired)
        return dict(decision, messages=messages)

    def tool_result(self, execution, result):
        touches = self.executions.pop(execution.token, [])
        agent = field(execution, 'agent');signal = execution.signal
        if not field(result, 'isError', False) and agent is not None and not signal.aborted:
            arguments = execution.arguments
            if execution.name in ('read', 'write', 'edit') and isinstance(arguments, dict):
                path = arguments.get('file_path')
                if isinstance(path, str) and path.strip(JS_WHITESPACE):touches.append((agent, path.strip(JS_WHITESPACE)))
        parent = field(execution, 'parent')
        if parent is not None:
            if touches:self.executions.setdefault(parent, []).extend(touches)
            return
        for owner, path in touches:self.project_touch(owner, path)


class AuthorizedAgentInstructionsPlugin(Plugin):
    id = '@deepseek-ai/dsh-agent-instructions'
    name = 'agent-instructions'
    inject = ['agents', 'workingDirectory']

    def apply(self, ctx):
        self.runtime = AuthorizedInstructionRuntime(ctx, self.config)
