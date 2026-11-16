"""Round-trip credential edits after pinned document admission."""
import copy
import io
import warnings

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import FileMark, YAMLError

from dsh.cordis.utils import _UNDEFINED
from dsh.credentials.document_current import DocumentLoader, _scalar, parse_credentials_document


def _pairs(loader, node):
    return [(_scalar(loader, key), key, value) for key, value in node.value if isinstance(key, yaml.ScalarNode)]


def _last_line(node):
    if isinstance(node, yaml.MappingNode) and not node.flow_style and node.value:
        return _last_line(node.value[-1][1])
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
        return _last_line(node.value[-1])
    return node.end_mark.line - (1 if node.end_mark.column == 0 else 0)


def _comment_text(source):
    return '\n'.join(line.lstrip()[1:].lstrip(' ') if line.lstrip().startswith('#') else line for line in source.splitlines()).strip('\n')


def _repair_flow_comments(root, node, loader, text):
    """Recover comments following flow separators that the RT parser omits."""
    known = set(); seen = set(); collections = []
    def tokens(item):
        if item is None or id(item) in seen: return
        seen.add(id(item))
        if hasattr(item, 'start_mark') and hasattr(item, 'value'):
            lines = item.value.splitlines()
            first = next((index for index, line in enumerate(lines) if '#' in line), None)
            if first is not None:
                for index, line in enumerate(lines[first:], first):
                    if '#' in line: known.add(item.start_mark.line+index-first)
        elif isinstance(item, (list, tuple)):
            for child in item: tokens(child)
        elif isinstance(item, dict):
            for child in item.values(): tokens(child)
    def visit(current, source):
        if current is None: return
        if hasattr(current, 'ca'):
            tokens(current.ca.comment); tokens(current.ca.items); tokens(current.ca.end)
        if isinstance(source, yaml.MappingNode) and hasattr(current, 'items'):
            children = [(name, child) for name, _, child in _pairs(loader, source)]
            if source.flow_style: collections.append((source, current, children))
            for name, child in children:
                if name in current: visit(current[name], child)
        elif isinstance(source, yaml.SequenceNode) and isinstance(current, list):
            children = list(enumerate(source.value))
            if source.flow_style: collections.append((source, current, children))
            for index, child in children: visit(current[index], child)
    visit(root, node)
    protected = [(item.start_mark.index, item.end_mark.index) for item in yaml.scan(text, Loader=DocumentLoader)
                 if isinstance(item, (yaml.ScalarToken, yaml.TagToken, yaml.AnchorToken, yaml.AliasToken))]
    offset = 0
    for line_number, line in enumerate(text.splitlines(True)):
        for column, char in enumerate(line):
            position = offset+column
            if char != '#' or any(start <= position < end for start, end in protected): continue
            if line_number not in known:
                candidates = [entry for entry in collections if entry[0].start_mark.index < position < entry[0].end_mark.index]
                if candidates:
                    source, current, children = min(candidates, key=lambda entry:entry[0].end_mark.index-entry[0].start_mark.index)
                    previous = [(key, child) for key, child in children if child.end_mark.index <= position]
                    comment = line[column:].rstrip('\r\n')
                    if previous:
                        key = previous[-1][0]
                        current.yaml_add_eol_comment(comment, key=key, column=column)
                        current.ca.items[key][2].start_mark = FileMark('<document>', position, line_number, column)
                    else: current.yaml_set_start_comment(comment[1:].lstrip(' '))
            break
        offset += len(line)


def _partition_comment(token, last_line):
    lines = token.value.splitlines(True)
    first = next((index for index, line in enumerate(lines) if line.strip()), 0)
    boundary = next((index for index in range(len(lines)) if token.start_mark.line+index-first > last_line), len(lines))
    return ''.join(lines[:boundary]), ''.join(lines[boundary:])


def _delete(root, section, key, nodes, root_names):
    mapping = root[section]
    keys = list(mapping)
    position = keys.index(key)
    previous = keys[position-1] if position else None
    following = keys[position+1] if position+1 < len(keys) else None
    current = mapping.ca.items.get(key)
    token = current[2] if current is not None else None
    suffix = ''
    if token is not None:
        _, suffix = _partition_comment(token, _last_line(nodes[key]))
    if previous is not None:
        prior = mapping.ca.items.get(previous)
        if prior is not None and prior[2] is not None:
            prior_token = prior[2]
            prefix, _ = _partition_comment(prior_token, _last_line(nodes[previous]))
            if prefix.strip():
                replacement = copy.copy(prior_token); replacement.value = prefix
                prior[2] = replacement
            else: prior[2] = None
    else:
        # Source removes the section-map annotation attached to its first entry.
        mapping.ca.comment = None
        parent_comment = root.ca.items.get(section)
        if parent_comment is not None: parent_comment[2] = parent_comment[3] = None
    del mapping[key]
    mapping.ca.items.pop(key, None)
    if not suffix.strip(): return
    if following is not None:
        mapping.yaml_set_comment_before_after_key(following, before=_comment_text(suffix), indent=2)
    elif previous is not None:
        prior = mapping.ca.items.setdefault(previous, [None, None, None, None])
        replacement = copy.copy(prior[2] if prior[2] is not None else token)
        replacement.value = (prior[2].value if prior[2] is not None else '\n')+suffix
        prior[2] = replacement
    else:
        position = root_names.index(section)
        if position+1 < len(root_names):
            root.yaml_set_comment_before_after_key(root_names[position+1], before=_comment_text(suffix))
        else:
            return suffix


def _render_edit(text, section, key, value=_UNDEFINED):
    """Return a next document; callers retain ownership of locking and persistence."""
    parse_credentials_document(text or '', '<document>')
    loader = DocumentLoader(text or '')
    try:
        node = loader.get_single_node()
        if node is not None and not isinstance(node, (yaml.MappingNode, yaml.SequenceNode)):
            raise ValueError('Expected a YAML collection as document contents')
        pairs = [] if node is None or not isinstance(node, yaml.MappingNode) else _pairs(loader, node)
        section_node = next((child for name, _, child in pairs if name == section), None)
        if section_node is not None and not isinstance(section_node, (yaml.MappingNode, yaml.SequenceNode)):
            raise ValueError('Expected YAML collection at '+section+'. Remaining path: '+key)
        parser = YAML(typ='rt', pure=True)
        parser.preserve_quotes = True
        parser.width = 1000000
        with warnings.catch_warnings(record=True):
            root = parser.load(text or '')
        if root is None:
            root = CommentedMap()
            if text and text.strip(): root.yaml_set_start_comment(_comment_text(text))
        elif text: _repair_flow_comments(root, node, loader, text)
        if 'version' not in root: root['version'] = 1
        if section not in root: root[section] = CommentedMap()
        mapping = root[section]
        trailing = ''
        if value is _UNDEFINED:
            if key in mapping:
                nodes = {name: child for name, _, child in _pairs(loader, section_node)}
                trailing = _delete(root, section, key, nodes, [name for name, _, _ in pairs]) or ''
        else:
            # Replacing a machine-written record discards its value-node comments.
            if section == 'records' and key in mapping:
                annotation = mapping.ca.items.get(key)
                if annotation is not None: annotation[2] = annotation[3] = None
            mapping[key] = value
        stream = io.StringIO()
        parser.dump(root, stream)
        result = stream.getvalue()+trailing
        # A renderer failure must be detected before its caller can replace disk.
        parse_credentials_document(result, '<document>')
        return result
    finally: loader.dispose()


def render_edit(text, section, key, value=_UNDEFINED):
    try: return _render_edit(text, section, key, value)
    except YAMLError:
        raise ValueError('credentials-local: could not edit the admitted document safely') from None
