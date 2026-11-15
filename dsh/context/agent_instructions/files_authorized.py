"""Abort-aware instruction discovery and bounded reads over optional ctx.fs."""
import asyncio
import hashlib
import inspect
import os
import stat

from dsh.context.agent_instructions.config_authorized import (
    JS_WHITESPACE, resolve_config, resolve_discovery_config, dsh_home_display, agents_home_display,
)
from dsh.context.agent_instructions.files import ancestor_chain, descendant_dirs_between
from dsh.context.agent_instructions.render_authorized import byte_length, utf8, disabled, render_agent_instruction_set
from dsh.context.agent_instructions.scope_authorized import (
    USER_GLOBAL_DIRECTORY, AGENTS_GLOBAL_DIRECTORY, USER_GLOBAL_FILE,
    scope_for_display_path, instruction_candidate_group, decode_scope_key, escape_project_display_path,
)


def check(signal):
    if signal is not None:signal.throwIfAborted()


def field(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def join(*parts):
    # node:path.join normalizes joined segments; an absolute later component
    # does not discard the preceding root as os.path.join would.
    return os.path.normpath(os.sep.join(part for part in parts if part))


def relative_display(root, path):
    try:value = os.path.relpath(path, root)
    except ValueError:value = path
    return escape_project_display_path('' if value == '.' else value)


def user_global_roots(config):
    return [dict(directory=USER_GLOBAL_DIRECTORY, home=config['dshHome'], display=dsh_home_display(config['dshHome'])),
            dict(directory=AGENTS_GLOBAL_DIRECTORY, home=config['agentsHome'], display=agents_home_display(config['agentsHome']))]


async def host_stat(path):
    return await asyncio.get_running_loop().run_in_executor(None, os.stat, path)


async def stat_file(path, filesystem=None, signal=None):
    try:
        if filesystem is None:
            check(signal);info = await host_stat(path);check(signal)
            return dict(kind='present', info=dict(size=info.st_size)) if stat.S_ISREG(info.st_mode) else dict(kind='absent')
        target = await filesystem.resolve(path, dict(signal=signal) if signal is not None else None);check(signal)
        info = await filesystem.stat(target, signal);check(signal)
        if field(info, 'type') != 'file':return dict(kind='absent')
        value = dict(target=target, version=field(info, 'version'))
        if field(info, 'size') is not None:value['size'] = field(info, 'size')
        return dict(kind='present', info=value)
    except Exception as error:
        check(signal)
        missing = filesystem is None and isinstance(error, (FileNotFoundError, NotADirectoryError))
        return dict(kind='absent' if missing else 'unavailable')


async def exists_as_marker(path, filesystem=None, signal=None):
    try:
        if filesystem is not None:
            target = await filesystem.resolve(path, dict(signal=signal) if signal is not None else None)
            return await filesystem.stat(target, signal) is not None
        check(signal);await host_stat(path);check(signal);return True
    except Exception as error:
        check(signal)
        if (getattr(error, 'code', None) == 'FS_NOT_FOUND' if filesystem is not None else isinstance(error, (FileNotFoundError, NotADirectoryError))):return False
        raise


async def find_project_root(cwd, markers, filesystem=None, signal=None):
    current = os.path.abspath(cwd)
    while True:
        for marker in markers:
            if await exists_as_marker(join(current, marker), filesystem, signal):return current
        parent = os.path.dirname(current)
        if parent == current:return os.path.abspath(cwd)
        current = parent


async def discover_instruction_files(options, filesystem=None):
    config = resolve_discovery_config(options);files=[];seen=set();signal=options.get('signal')
    async def add(path, display):
        probe = await stat_file(path, filesystem, signal)
        if probe['kind'] == 'present' and path not in seen:
            seen.add(path);files.append(dict(absolutePath=path, displayPath=display, **probe['info']))
    for root in user_global_roots(config):
        await add(join(root['home'], USER_GLOBAL_FILE), root['display'] + '/' + USER_GLOBAL_FILE)
    cwd = os.path.abspath(options['cwd'])
    project_root = options.get('projectRoot')
    if project_root is None:project_root = await find_project_root(cwd, config['projectRootMarkers'], filesystem, signal)
    for directory in ancestor_chain(project_root, cwd):
        for candidates in (config['instructionFileCandidates'], config['localInstructionFileCandidates']):
            for candidate in candidates:
                path = join(directory, candidate);await add(path, relative_display(project_root, path))
    return files


async def discover_baseline_instruction_files(options):
    return [dict(absolutePath=file['absolutePath'], displayPath=file['displayPath']) for file in await discover_instruction_files(options)]


async def host_text_chunks(path, signal):
    loop = asyncio.get_running_loop()
    stream = await loop.run_in_executor(None, lambda:open(path, 'r', encoding='utf-8', errors='replace', newline=''))
    try:
        while True:
            check(signal);chunk = await loop.run_in_executor(None, stream.read, 65536)
            if not chunk:break
            yield chunk
    finally:await loop.run_in_executor(None, stream.close)


async def read_bounded(file, maximum, filesystem=None, signal=None):
    check(signal)
    if file.get('size') is not None and file['size'] > maximum:return None
    try:
        chunks = (host_text_chunks(file['absolutePath'], signal) if filesystem is None or file.get('target') is None
                  else await filesystem.streamText(file['target'], signal))
        parts=[];size=0;exhausted=False
        try:
            async for chunk in chunks:
                check(signal);size += byte_length(chunk)
                if size > maximum:return None
                parts.append(chunk)
            exhausted=True
        finally:
            if not exhausted:
                close = getattr(chunks, 'aclose', None)
                if close is not None:
                    result = close()
                    if inspect.isawaitable(result):await result
        check(signal);return ''.join(parts)
    except Exception:
        check(signal);return None


def trimmed_digest(content):
    return hashlib.sha1(utf8(content.strip(JS_WHITESPACE))).hexdigest()


def dedup_instruction_files_by_candidate_group(files):
    groups={};kept=[]
    for file in files:
        group = instruction_candidate_group(scope_for_display_path(file['displayPath']));digests = groups.setdefault(group, set())
        digest = trimmed_digest(file['content'])
        if digest not in digests:digests.add(digest);kept.append(file)
    return kept


async def load_baseline_instruction_set(options, filesystem=None):
    config = resolve_config(options)
    if disabled(config['maxBytes']) or disabled(config['maxSourceBytes']):return None
    loaded=[]
    for file in await discover_instruction_files(options, filesystem):
        content = await read_bounded(file, config['maxSourceBytes'], filesystem, options.get('signal'))
        if content is not None:
            value = dict(absolutePath=file['absolutePath'], displayPath=file['displayPath'], content=content)
            if 'version' in file:value['version'] = file['version']
            loaded.append(value)
    kept = dedup_instruction_files_by_candidate_group(loaded)
    if not kept and options.get('replacePreviousBaseline') is not True:return None
    result = render_agent_instruction_set(kept, dict(maxBytes=config['maxBytes'], replacePreviousBaseline=options.get('replacePreviousBaseline')))
    paths = {file['absolutePath'] for file in kept}
    return dict(result, observed=loaded, deduped=[file for file in loaded if file['absolutePath'] not in paths])


async def load_baseline_instructions(options, filesystem=None):
    value = await load_baseline_instruction_set(options, filesystem)
    return value['rendered'] if value is not None else None


def scope_instruction_file(scope, project_root, resolved):
    decoded = decode_scope_key(scope);directory, candidate = decoded['directory'], decoded['candidateName']
    root = next((root for root in user_global_roots(resolved) if root['directory'] == directory), None)
    path = join(root['home'] if root is not None else project_root if directory == '.' else join(project_root, directory), candidate)
    return dict(absolutePath=path, displayPath=root['display'] + '/' + candidate if root is not None else relative_display(project_root, path))


async def probe_scope_instruction(scope, project_root, resolved, filesystem, signal=None):
    candidate = scope_instruction_file(scope, project_root, resolved)
    try:
        target = await filesystem.resolve(candidate['absolutePath'], dict(signal=signal) if signal is not None else None)
        info = await filesystem.stat(target, signal)
    except Exception:
        check(signal);return dict(kind='unavailable')
    if field(info, 'type') != 'file':return dict(kind='absent')
    file = dict(candidate, target=target, version=field(info, 'version'))
    if field(info, 'size') is not None:file['size'] = field(info, 'size')
    return dict(kind='present', file=file)


async def read_scope_instruction(file, maximum, filesystem, signal=None):
    content = await read_bounded(file, maximum, filesystem, signal)
    return None if content is None else dict(absolutePath=file['absolutePath'], displayPath=file['displayPath'], content=content, version=file['version'])
