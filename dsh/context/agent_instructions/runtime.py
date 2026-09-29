"""Durable workspace instructions in the canonical Agent pre-step pipeline."""
import asyncio
import os
import weakref
from dsh.core.cancellation import aborted
from dsh.llm.message import create_user_message
from .config import workspace_baseline_identity
from .digest import instruction_content_sha1
from .files import ancestor_chain, descendant_dirs_between, relative_display, user_global_display_path, dedup_instruction_files_by_directory
from .render import instruction_scope_key, render_workspace_instruction_set, render_instruction_changes


def visible_messages(agent):
    return [agent.session.events[seq]['data'] for seq in agent.session.surface.nodes
            if agent.session.events[seq]['type'] == 'user/message']


class InstructionRuntime:
    def __init__(self, ctx, config):
        self.ctx, self.config = ctx, config
        self.touches = weakref.WeakKeyDictionary()
        self.executions = {}
        ctx.on('agent/pre-step', self.pre_step)
        ctx.on('tools/result', self.tool_result)
        ctx.effect(lambda: self.executions.clear)

    def tool_result(self, execution, result):
        token = getattr(execution, 'token', None)
        touches = self.executions.pop(token, [])
        agent = getattr(execution, 'agent', None)
        args = getattr(execution, 'arguments', {})
        error = result.get('isError', False) if isinstance(result, dict) else getattr(result, 'isError', False)
        if agent is not None and not error and not aborted(getattr(execution, 'signal', None)):
            if getattr(execution, 'name', '') in ('read', 'write', 'edit', 'str_replace_editor') and isinstance(args, dict):
                path = args.get('file_path') or args.get('path')
                if isinstance(path, str) and path.strip():
                    touches.append((agent.session, path.strip()))
        parent = getattr(execution, 'parent', None)
        if parent is not None:
            self.executions.setdefault(parent, []).extend(touches)
        else:
            for session, path in touches:
                self.touches.setdefault(session, set()).add(path)

    async def compose(self, agent, claimed, signal):
        cfg = self.config
        fs = self.ctx.get('fs')
        if fs is None or cfg.max_bytes <= 0 or cfg.max_source_bytes <= 0:
            return None
        cwd = os.path.abspath(agent.session.header.cwd or os.getcwd())
        root = cwd
        while True:
            if any([await fs.stat(os.path.join(root, marker), signal) is not None for marker in cfg.project_root_markers]):
                break
            parent = os.path.dirname(root)
            if parent == root:
                root = cwd
                break
            root = parent
        identity = workspace_baseline_identity(cfg, cwd, root)
        authority = visible_messages(agent) + list(claimed)
        sources = [m.get('source', {}) for m in authority if m.get('source', {}).get('kind') == 'agent-instructions']
        baseline = next((s for s in reversed(sources) if s.get('baseline')), None)
        active = {}
        for source in sources:
            for change in source.get('changes', []):
                if change['action'] == 'remove':
                    active.pop(change['scope'], None)
                else:
                    active[change['scope']] = change
        paths = {os.path.join(cfg.dsh_home, 'AGENTS.md'): user_global_display_path(cfg.dsh_home)}
        directories = ancestor_chain(root, cwd)
        touched = self.touches.get(agent.session, set())
        for path in touched:
            directories.extend(descendant_dirs_between(root, path))
        for directory in directories:
            for candidate in cfg.instruction_file_candidates + cfg.local_instruction_file_candidates:
                path = os.path.join(directory, candidate)
                paths[path] = relative_display(root, path)
        for change in active.values():
            display = change['path']
            paths.setdefault(os.path.join(root, display) if not os.path.isabs(display) else display, display)
        loaded = []
        for path, display in paths.items():
            info = await fs.stat(path, signal)
            if info is None or info.type != 'file' or info.size > cfg.max_source_bytes:
                continue
            text = await fs.readText(path, signal)
            if len(text.encode('utf-8')) <= cfg.max_source_bytes:
                loaded.append(dict(absolutePath=path, displayPath=display, content=text))
        loaded = dedup_instruction_files_by_directory(loaded)
        if aborted(signal):
            raise asyncio.CancelledError()
        if baseline is None or baseline.get('baselineIdentity') != identity:
            rendered = render_workspace_instruction_set(loaded, dict(maxBytes=cfg.max_bytes, replacePreviousBaseline=baseline is not None))
            if not loaded and baseline is None:
                return None
            changes = [dict(action='set', scope=instruction_scope_key(f['displayPath']), path=f['displayPath'], digest=instruction_content_sha1(f['content'])) for f in rendered['included']]
            represented = {c['scope'] for c in changes}
            changes = [dict(action='remove', scope=k, path=v['path']) for k, v in active.items() if k not in represented] + changes
            source = dict(kind='agent-instructions', form='instructions', baseline=True, baselineIdentity=identity, changes=changes)
            text = rendered['rendered']['text']
        else:
            current = {instruction_scope_key(f['displayPath']): f for f in loaded}
            items = []
            for scope, file in current.items():
                digest = instruction_content_sha1(file['content'])
                if active.get(scope, {}).get('digest') == digest:
                    continue
                items.append(dict(file=file, change=dict(action='set', scope=scope, path=file['displayPath'], digest=digest)))
            for scope, prior in active.items():
                if scope not in current:
                    items.append(dict(file=dict(absolutePath=prior['path'], displayPath=prior['path'], content=''), change=dict(action='remove', scope=scope, path=prior['path'])))
            if not items:
                return None
            rendered = render_instruction_changes(items, cfg.max_bytes)
            text = rendered['text']
            source = dict(kind='agent-instructions', form='instructions', changes=rendered['changes'])
        return create_user_message(dict(content=[dict(type='text', text=text)], source=source)) if text else None

    async def pre_step(self, payload, next_fn):
        decision = await next_fn()
        agent = payload['agent']
        claimed = payload['messages']
        pending = [m for m in agent.inbox.next_step if m.get('source', {}).get('kind') == 'agent-instructions']
        desired = await self.compose(agent, claimed, payload.get('signal'))
        for message in pending:
            agent.inbox.remove(message['id'])
        if decision['kind'] == 'reject' or (payload['step'] == 1 and not decision['messages']):
            if desired:
                agent.inbox.prepend('next-step', desired)
            return decision
        if desired is None:
            return decision
        messages = list(decision['messages'])
        position = max([i for i, m in enumerate(messages) if m in claimed] or [-1]) + 1
        messages.insert(position, desired)
        return dict(decision, messages=messages)
