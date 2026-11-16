"""Source-preserving edits of explicit pending dependency build permissions.

LEGAL_ADAPTATION: PyYAML events replace Node YAML document nodes. Untouched
settings/comments/anchors retain their source bytes; changed flow formatting
is not a byte-for-byte Node serializer claim. This module never runs scripts.
"""
import json
import os
import re
from types import SimpleNamespace as NS
from urllib.parse import urlsplit

import yaml

from dsh.boot.plugin_install_spec import _url_host
from dsh.boot.plugin_switch import _syntax_end, _line_end
from dsh.host.http_proxy_policy import JS_SPACE
from dsh.util.atomic_write import write_file_atomic

UNDECIDED_BUILD = 'set this to true or false'
_IGNORED = re.compile(r'\bIgnored build scripts: ([^\r\n\u2028\u2029]+)', re.ASCII)
_GIT_PREPARE = re.compile(r'ERR_PNPM_GIT_DEP_PREPARE_NOT_ALLOWED[\s\S]*?^allowBuilds:\r?\n[ \t]+([^\r\n\u2028\u2029]+?): true(?=\r?$)', re.M)


def carries_credential(key):
    at = key.find('@git+')
    if at < 0:return False
    address = key[at+5:].split('#', 1)[0]
    try:
        _url_host(address)
        parsed = urlsplit(address)
        return bool(parsed.password or (parsed.username and parsed.scheme.lower() in ('http', 'https')))
    except (ValueError, TypeError):return False


def blocked_build_names(output):
    ignored, git = _IGNORED.search(output), _GIT_PREPARE.search(output)
    names = ([] if ignored is None else ignored[1].split(','))+([] if git is None else [git[1]])
    return [name for name in (name.strip(JS_SPACE) for name in names)
            if name and not re.search(r'[*?]', name) and not carries_credential(name)]


def _string(node):
    event = node.event
    if not isinstance(event, yaml.ScalarEvent):return None
    if event.tag == 'tag:yaml.org,2002:str' or event.style is not None:return event.value
    if event.tag is not None and event.tag != 'tag:yaml.org,2002:str':return None
    if (event.value == '' or event.value in ('null', 'Null', 'NULL', '~', 'true', 'True', 'TRUE', 'false', 'False', 'FALSE')
        or re.fullmatch(r'[-+]?(?:[0-9][0-9_]*(?:\.[0-9_]*)?(?:[eE][-+]?[0-9]+)?|\.[0-9_]+(?:[eE][-+]?[0-9]+)?|\.inf|\.Inf|\.INF|\.nan|\.NaN|\.NAN|0[xX][0-9a-fA-F]+|0[oO][0-7]+)', event.value)):
        return None
    return event.value


def _policy(text):
    events = iter(yaml.parse(text))
    def read(event):
        node = NS(event=event, children=[], end=event.end_mark.index)
        if isinstance(event, yaml.CollectionStartEvent):
            for child in events:
                if isinstance(child, (yaml.SequenceEndEvent, yaml.MappingEndEvent)):
                    node.end = child.end_mark.index
                    break
                node.children.append(read(child))
        return node
    root = None
    for event in events:
        if isinstance(event, (yaml.ScalarEvent, yaml.AliasEvent, yaml.CollectionStartEvent)):
            if root is not None:raise ValueError('Workspace must contain one YAML document')
            root = read(event)
    def validate(node):
        if isinstance(node.event, yaml.MappingStartEvent):
            keys = []
            for key in node.children[::2]:
                if isinstance(key.event, yaml.ScalarEvent):
                    identity = (_string(key), key.event.value) if _string(key) is None else ('string', _string(key))
                    if identity in keys:raise ValueError('Map keys must be unique')
                    keys.append(identity)
        for child in node.children:validate(child)
    if root is None or not isinstance(root.event, yaml.MappingStartEvent):raise ValueError('pnpm-workspace.yaml must be a YAML mapping')
    validate(root)
    builds = next((value for key, value in zip(root.children[::2], root.children[1::2]) if _string(key) == 'allowBuilds'), None)
    if (builds is not None and isinstance(builds.event, yaml.ScalarEvent) and builds.event.style is None
            and builds.event.value in ('', 'null', 'Null', 'NULL', '~')):
        builds = None
    if builds is not None:
        if not isinstance(builds.event, yaml.MappingStartEvent):raise ValueError('allowBuilds must be a YAML mapping')
        def unshared(node):
            if isinstance(node.event, yaml.AliasEvent) or getattr(node.event, 'anchor', None):
                raise ValueError('allowBuilds must not contain YAML anchors or aliases')
            for child in node.children:unshared(child)
        unshared(builds)
    pairs = [] if builds is None else list(zip(builds.children[::2], builds.children[1::2]))
    keys = [name for name in (_string(key) for key, _ in pairs) if name is not None]
    pending = [name for key, value in pairs for name in [_string(key)]
               if name is not None and not re.search('[*?]', name) and _string(value) == UNDECIDED_BUILD]
    return root, builds, pairs, keys, pending


def _set(text, names, value):
    root, builds, pairs, _, _ = _policy(text)
    changes = []
    added = list(dict.fromkeys(names))
    for key, current in pairs:
        name = _string(key)
        if name in added:
            changes.append((current.event.start_mark.index, current.end, value))
            added.remove(name)
    if added:
        flow = ', '.join(json.dumps(name, ensure_ascii=False)+': '+value for name in added)
        if builds is None:
            if any(_string(key) == 'allowBuilds' for key in root.children[::2]):
                raise ValueError('Cannot add keys below null allowBuilds')
            if root.event.flow_style:
                changes.append((root.end-1, root.end-1, (', ' if root.children else '')+'allowBuilds: { '+flow+' }'))
            else:
                end = _line_end(text, _syntax_end(root))
                changes.append((end, end, '\nallowBuilds:\n'+''.join('  '+json.dumps(name, ensure_ascii=False)+': '+value+'\n' for name in added)))
        elif builds.event.flow_style:
            changes.append((builds.end-1, builds.end-1, (', ' if builds.children else '')+flow))
        else:
            end = _line_end(text, _syntax_end(builds))
            indent = ' '*builds.event.start_mark.column
            changes.append((end, end, '\n'+'\n'.join(indent+json.dumps(name, ensure_ascii=False)+': '+value for name in added)))
    for start, end, replacement in sorted(changes, reverse=True):text = text[:start]+replacement+text[end:]
    _policy(text)
    return text


def _read(directory):
    try:
        with open(os.path.join(directory, 'pnpm-workspace.yaml'), encoding='utf-8', errors='replace', newline='') as stream:return stream.read()
    except FileNotFoundError:return '{}\n'


async def record_pending_builds(directory, output):
    text = _read(directory)
    _, _, _, keys, pending = _policy(text)
    added = [name for name in blocked_build_names(output) if name not in keys]
    if added:
        await write_file_atomic(os.path.join(directory, 'pnpm-workspace.yaml'), _set(text, added, json.dumps(UNDECIDED_BUILD)), mode=0o600)
    return pending+added


async def approve_builds(directory, names):
    text = _read(directory)
    _, _, _, _, pending = _policy(text)
    if any(name not in pending for name in names):
        from dsh.boot.plugin_manager_current import ManagementFailure
        raise ManagementFailure('stale-approval')
    if names:await write_file_atomic(os.path.join(directory, 'pnpm-workspace.yaml'), _set(text, names, 'true'), mode=0o600)
