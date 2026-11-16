"""Persistent plugin enablement using source-preserving YAML token edits.

LEGAL_ADAPTATION: Python uses PyYAML events instead of Node YAML's mutable
document nodes. Untouched syntax stays byte-for-byte; formatting normalization
of changed flow collections is intentionally not a byte parity claim.
"""
import re
from types import SimpleNamespace as NS

import yaml

from dsh.boot.config_editor import PatchLoader, flatten
from dsh.boot.profile import compose_entries
from dsh.boot.profile_context import read_bundle_patches
from dsh.boot.runtime_resolution import _field
from dsh.util.atomic_write import write_file_atomic


def _document(text):
    events = iter(yaml.parse(text, Loader=PatchLoader))
    def node(event):
        result = NS(event=event, children=[], end=event.end_mark.index)
        if isinstance(event, (yaml.SequenceStartEvent, yaml.MappingStartEvent)):
            for child in events:
                if isinstance(child, (yaml.SequenceEndEvent, yaml.MappingEndEvent)):
                    result.end = child.end_mark.index
                    break
                result.children.append(node(child))
        return result
    root = None
    for event in events:
        if isinstance(event, (yaml.ScalarEvent, yaml.AliasEvent, yaml.CollectionStartEvent)):
            if root is not None:
                raise ValueError('Profile patch must be a single YAML document')
            root = node(event)
    rows = yaml.load(text, Loader=PatchLoader)
    if not isinstance(rows, list) or root is None or not isinstance(root.event, yaml.SequenceStartEvent):
        raise ValueError('Profile patch must be a YAML sequence')
    def validate(current):
        if isinstance(current.event, yaml.MappingStartEvent):
            seen = set()
            for key in current.children[::2]:
                if isinstance(key.event, yaml.ScalarEvent):
                    # Quoting does not make two identical field names unique.
                    identity = key.event.value
                    if identity in seen:
                        raise ValueError('Map keys must be unique')
                    seen.add(identity)
        for child in current.children:
            validate(child)
    validate(root)
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('Profile patch entries must be mappings')
    return rows, root


def _pairs(node):
    return [(key.event.value, key, value) for key, value in zip(node.children[::2], node.children[1::2])
            if isinstance(key.event, yaml.ScalarEvent)]


def _syntax_end(node):
    if isinstance(node.event, yaml.CollectionStartEvent) and not node.event.flow_style and node.children:
        return _syntax_end(node.children[-1])
    return node.end


def _line_end(text, index):
    found = text.find('\n', index)
    return len(text) if found < 0 else found


def edit_enabled_document(text, identity, name, enabled, bundle_patches):
    rows, document = _document(text)
    candidates = [index for index, row in enumerate(rows)
        if isinstance(document.children[index].event, yaml.MappingStartEvent)
        and row.get('id') == identity and 'insert' not in row
        and (not row.get('name') or row['name'] == name)]
    def implied(index):
        composed = flatten(compose_entries([[*bundle_patches, *rows[:index], *rows[index+1:]]]))
        matches = [row for row in composed if row.get('id') == identity]
        # Literal comparison only; !!js conditions cannot imply a fixed value.
        disabled = matches[-1].get('disabled') if matches else None
        disabled = False if disabled is None else disabled
        return bool(matches) and type(disabled) is bool and disabled is (not enabled)
    target = candidates[-1] if candidates else None
    boolean = 'false' if enabled else 'true'
    if target is not None:
        current = document.children[target]
        pairs = _pairs(current)
        only_switch = not current.event.anchor and all(
            field in ('id', 'disabled') and isinstance(key.event, yaml.ScalarEvent)
            and isinstance(value.event, yaml.ScalarEvent) and not key.event.anchor and not value.event.anchor
            for field, key, value in pairs)
        if only_switch and implied(target):
            if document.event.flow_style:
                start, end = current.event.start_mark.index, current.end
                # Remove the adjacent comma without touching another item.
                if target + 1 < len(rows):
                    end = document.children[target+1].event.start_mark.index
                elif target:
                    start = text.rfind(',', document.children[target-1].end, start)
                return True, text[:start] + text[end:]
            start = text.rfind('\n', 0, current.event.start_mark.index) + 1
            end = _line_end(text, _syntax_end(current))
            end = end + 1 if end < len(text) else end
            prefix, suffix = text[:start], text[end:]
            if len(rows) == 1:
                return True, prefix + '[]\n' + ('\n' if suffix else '') + suffix
            if target == len(rows)-1:
                comment = re.search(r'((?:[ \t]*#[^\n]*\n)+)$', prefix)
                if comment:
                    prefix = prefix[:comment.start()] + '\n' + comment.group()
            return True, prefix + suffix
        if type(rows[target].get('disabled')) is bool and rows[target]['disabled'] is (not enabled):
            return False, text
        value = next((value for field, _, value in pairs if field == 'disabled'), None)
        if value is not None:
            start, end = value.event.start_mark.index, value.end
            if isinstance(value.event, yaml.ScalarEvent):
                tokens = [token for token in yaml.scan(text, Loader=PatchLoader)
                          if isinstance(token, yaml.ScalarToken) and start <= token.start_mark.index < end]
                if tokens:
                    start, end = tokens[-1].start_mark.index, tokens[-1].end_mark.index
            return True, text[:start] + boolean + text[end:]
        if current.event.flow_style:
            end = current.end-1
            return True, text[:end] + (', ' if pairs else '') + 'disabled: '+boolean + text[end:]
        end = _line_end(text, _syntax_end(current))
        indent = current.event.start_mark.column
        return True, text[:end] + '\n' + ' '*indent + 'disabled: '+boolean + text[end:]
    if implied(len(rows)):
        return False, text
    # New ids are YAML strings even when they resemble booleans or punctuation.
    scalar = yaml.safe_dump(identity, default_flow_style=True, allow_unicode=True).split('\n...')[0].strip()
    if document.event.flow_style and rows:
        end = document.end-1
        return True, text[:end] + ', { id: '+scalar+', disabled: '+boolean+' }' + text[end:]
    item = '- id: '+scalar+'\n  disabled: '+boolean+'\n'
    if not rows:
        return True, text[:document.event.start_mark.index] + item + text[document.end:]
    end = _line_end(text, _syntax_end(document))
    if end < len(text):
        end += 1
    return True, text[:end] + ('' if text[:end].endswith('\n') else '\n') + item + text[end:]


async def write_plugin_enabled(profile, identity, name, enabled):
    filename = _field(profile, 'patchPath')
    try:
        with open(filename, 'r', encoding='utf-8') as stream:
            text = stream.read()
    except FileNotFoundError:
        text = '[]\n'
    # Validate before reading the bundle graph or publishing any bytes.
    _document(text)
    changed, content = edit_enabled_document(text, identity, name, enabled, read_bundle_patches('dsh', profile))
    if changed:
        await write_file_atomic(filename, content, mode=0o600)
    return changed


writePluginEnabled = write_plugin_enabled
