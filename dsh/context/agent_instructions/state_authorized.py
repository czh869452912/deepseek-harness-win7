"""Session-visible instruction reconciliation with deferred rendered cache updates."""
import hashlib

from dsh.llm.message import create_user_message
from .files_authorized import (
    ancestor_chain, descendant_dirs_between, find_project_root, relative_display,
    probe_scope_instruction, read_scope_instruction, scope_instruction_file, trimmed_digest, field,
)
from .render_authorized import render_instruction_changes, utf8
from .scope_authorized import (
    candidate_scope_key, decode_scope_key, instruction_candidate_group,
    instruction_scope_key, is_user_global_directory, USER_GLOBAL_DIRECTORIES, USER_GLOBAL_FILE,
)

name = 'agent-instructions'


def content_sha1(content):
    return hashlib.sha1(utf8(content)).hexdigest()


def agent_instructions_message(text, changes=None):
    return create_user_message(dict(content=[dict(type='text', text=text)],
        source=dict(kind=name, form='instructions', changes=[] if changes is None else changes)))


def is_instruction_source(source):
    return isinstance(source, dict) and source.get('kind') == name and isinstance(source.get('changes'), list)


def instruction_changes(source):
    changes = []
    for value in source['changes']:
        if not isinstance(value, dict) or value.get('action') not in ('set', 'replace', 'remove'):continue
        if not isinstance(value.get('scope'), str) or not isinstance(value.get('path'), str):continue
        if 'digest' in value and not isinstance(value['digest'], str):continue
        changes.append({key:value[key] for key in ('action', 'scope', 'path', 'digest') if key in value})
    return changes


def visible_instruction_changes(agent, authority_messages):
    visible = {}
    session = agent.session
    for seq in session.surface.nodes:
        event = session.eventAt(seq)
        if event is None or field(event, 'type') != 'user/message':continue
        source = field(field(event, 'data'), 'source')
        if is_instruction_source(source):
            for change in instruction_changes(source):visible[change['scope']] = change
    for message in authority_messages:
        source = field(message, 'source')
        if is_instruction_source(source):
            for change in instruction_changes(source):visible[change['scope']] = change
    return visible


def baseline_instruction_state(files):
    changes, versions = {}, {}
    for file in files:
        digest = content_sha1(file['content']);scope = instruction_scope_key(file['displayPath'])
        changes[scope] = dict(action='set', scope=scope, path=file['displayPath'], digest=digest)
        if 'version' in file:
            versions[scope] = dict(path=file['displayPath'], version=file['version'], digest=digest,
                trimmedDigest=trimmed_digest(file['content']))
    return dict(changes=changes, versions=versions)


def retained_instruction_version_updates(updates, rendered_changes):
    return [update for update in updates if any(all(update['change'].get(key) == change.get(key)
        for key in ('action', 'scope', 'path', 'digest')) for change in rendered_changes)]


def version_states_for(session, cache):
    if session not in cache:cache[session] = {}
    return cache[session]


def apply_instruction_version_updates(session, updates, cache):
    if not updates:return
    states = version_states_for(session, cache)
    for update in updates:
        if 'state' not in update:states.pop(update['change']['scope'], None)
        else:states[update['change']['scope']] = update['state']
    if not states:cache.pop(session, None)


async def reconcile_instruction_context(agent, resolved, version_cache, filesystem, options):
    session = agent.session;effective = visible_instruction_changes(agent, options['authorityMessages'])
    cwd = options['cwd'];signal = options.get('signal')
    root = options.get('projectRoot')
    if root is None:root = await find_project_root(cwd, resolved['projectRootMarkers'], filesystem, signal)
    scopes, baseline_scopes = {}, {}
    def add_dir(target, directory):
        for candidate in resolved['instructionFileCandidates'] + resolved['localInstructionFileCandidates']:
            target[candidate_scope_key(directory, candidate)] = None
    def add_project(target, directory):add_dir(target, relative_display(root, directory) or '.')
    for directory in USER_GLOBAL_DIRECTORIES:baseline_scopes[candidate_scope_key(directory, USER_GLOBAL_FILE)] = None
    for directory in ancestor_chain(root, cwd):add_project(baseline_scopes, directory)
    include = options['includeBaselineScopes']
    if include:scopes.update(baseline_scopes)
    for message in options['scopeMessages']:
        source = field(message, 'source')
        if not is_instruction_source(source):continue
        for change in instruction_changes(source):
            if include or change['scope'] not in baseline_scopes:scopes[change['scope']] = None
    for scope in effective:
        if not include and scope in baseline_scopes:continue
        directory = decode_scope_key(scope)['directory']
        if is_user_global_directory(directory):scopes[candidate_scope_key(directory, USER_GLOBAL_FILE)] = None
        else:add_dir(scopes, directory)
    for path in options['touchedPaths']:
        for directory in descendant_dirs_between(cwd, path):add_project(scopes, directory)

    versions = version_states_for(session, version_cache)
    seen, kept, items, updates, groups = set(), {}, [], [], {}
    def register(group, digest):
        values = kept.setdefault(group, set());duplicate = digest in values;values.add(digest);return duplicate
    def remove(scope, path, state=None):
        change = dict(action='remove', scope=scope, path=path)
        items.append(dict(change=change, file=dict(absolutePath='removed:'+scope, displayPath=path, content='')))
        updates.append(dict(change=change, **({} if state is None else dict(state=state))))
    for scope in scopes:groups.setdefault(instruction_candidate_group(decode_scope_key(scope)['directory']), []).append(scope)
    for group, group_scopes in groups.items():
        probed = []
        for scope in group_scopes:
            if scope in baseline_scopes and scope in options.get('excludedBaselineScopes', ()):
                previous = effective.get(scope)
                if previous is None or previous['action'] == 'remove':versions.pop(scope, None)
                else:remove(scope, previous['path'])
            else:probed.append(scope)
        item_start, update_start = len(items), len(updates)
        prior = {scope:versions.get(scope) for scope in probed}
        def rollback():
            del items[item_start:];del updates[update_start:]
            for scope, value in prior.items():
                if value is None:versions.pop(scope, None)
                else:versions[scope] = value
            for scope in probed:seen.add(scope_instruction_file(scope, root, resolved)['absolutePath'])
            kept.pop(group, None)
        for scope in probed:
            previous = effective.get(scope)
            probe = await probe_scope_instruction(scope, root, resolved, filesystem, signal)
            if probe['kind'] == 'unavailable':rollback();break
            if probe['kind'] == 'absent':
                if previous is None or previous['action'] == 'remove':versions.pop(scope, None)
                else:remove(scope, previous['path'])
                continue
            probed_file = probe['file']
            if probed_file['absolutePath'] in seen:continue
            seen.add(probed_file['absolutePath']);cached = versions.get(scope)
            if cached is not None and cached['path'] == probed_file['displayPath'] and cached['version'] == probed_file['version']:
                rendered = previous is not None and previous['action'] != 'remove' and previous['path'] == cached['path'] and previous.get('digest') == cached['digest']
                if rendered:
                    if register(group, cached['trimmedDigest']):remove(scope, previous['path'], cached)
                    continue
                if (previous is None or previous['action'] == 'remove') and cached['trimmedDigest'] in kept.get(group, ()):continue
            file = await read_scope_instruction(probed_file, resolved['maxSourceBytes'], filesystem, signal)
            if file is None:rollback();break
            digest = content_sha1(file['content']);trimmed = trimmed_digest(file['content'])
            state = dict(path=file['displayPath'], version=probed_file['version'], digest=digest, trimmedDigest=trimmed)
            if register(group, trimmed):
                if previous is not None and previous['action'] != 'remove':remove(scope, previous['path'], state)
                else:versions[scope] = state
                continue
            if previous is not None and previous['action'] != 'remove' and previous['path'] == file['displayPath'] and previous.get('digest') == digest:
                versions[scope] = state;continue
            change = dict(action='set' if previous is None or previous['action'] == 'remove' else 'replace', scope=scope, path=file['displayPath'], digest=digest)
            items.append(dict(change=change, file=file));updates.append(dict(change=change, state=state))
    if not items:return None
    rendered = render_instruction_changes(items, resolved['maxBytes'])
    if not rendered['text'] or not rendered['changes']:return None
    return dict(context=agent_instructions_message(rendered['text'], rendered['changes']),
        versionUpdates=retained_instruction_version_updates(updates, rendered['changes']))
