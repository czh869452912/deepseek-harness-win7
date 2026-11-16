"""Pinned credentials document admission; diagnostics never quote YAML source."""
import math
import re
import base64

import yaml

from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _js_own_enumerable_keys, js_to_string
from dsh.credentials.credentials import credential_ref, parse_credential_key
from dsh.credentials.credentials_local import assert_json_value


class _DocumentFailure(Exception):
    def __init__(self, code, mark):
        self.code = code
        self.mark = mark


class _Alias(yaml.Node):
    def __init__(self, event, source):
        super().__init__('alias', source, event.start_mark, event.end_mark)
        self.source_name = event.anchor


class DocumentLoader(yaml.SafeLoader):
    """Core YAML 1.2 scalars and duplicate detection, independent of YAML 1.1 defaults."""
    yaml_implicit_resolvers = {key: [(tag, pattern) for tag, pattern in rows
        if tag not in ('tag:yaml.org,2002:bool', 'tag:yaml.org,2002:int',
                       'tag:yaml.org,2002:float', 'tag:yaml.org,2002:timestamp', 'tag:yaml.org,2002:merge')]
        for key, rows in yaml.SafeLoader.yaml_implicit_resolvers.items()}

    def __init__(self, stream):
        super().__init__(stream)
        self.legacy = bool(re.search(r'^%YAML 1\.1\s*$', stream, re.MULTILINE))
        if self.legacy:
            self.yaml_implicit_resolvers = yaml.SafeLoader.yaml_implicit_resolvers

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            event = self.get_event()
            return _Alias(event, self.anchors.get(event.anchor))
        anchor = self.peek_event().anchor
        # YAML permits a later anchor to replace the name for later aliases.
        if anchor in self.anchors: del self.anchors[anchor]
        node = super().compose_node(parent, index)
        if anchor is not None: node.dsh_anchor = anchor
        return node


def _integer(loader, node):
    value = loader.construct_scalar(node)
    prefix = value.lstrip('+-').lower()[:2]
    number = loader.construct_yaml_int(node) if loader.legacy else int(value, 0 if prefix in ('0o', '0x') else 10)
    if abs(number) <= 2**53: return number
    try: return float(number)
    except OverflowError: return math.inf if number > 0 else -math.inf


DocumentLoader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|True|TRUE|false|False|FALSE)$'), list('tTfF'))
DocumentLoader.add_implicit_resolver('tag:yaml.org,2002:int', re.compile(r'^[-+]?(?:[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$'), list('-+0123456789'))
DocumentLoader.add_implicit_resolver('tag:yaml.org,2002:float', re.compile(
    r'^[-+]?(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?|[0-9]+[eE][-+]?[0-9]+|\.inf|\.Inf|\.INF|\.nan|\.NaN|\.NAN)$'), list('-+0123456789.'))
DocumentLoader.add_constructor('tag:yaml.org,2002:int', _integer)


def _flow_key(node):
    if isinstance(node, _Alias): return '*'+node.source_name
    if isinstance(node, yaml.SequenceNode): return '[ '+', '.join(_flow_key(item) for item in node.value)+' ]'
    if isinstance(node, yaml.MappingNode): return '{ '+', '.join(_flow_key(key)+': '+_flow_key(value) for key, value in node.value)+' }'
    if node.style == '"': return stringify_json(node.value)
    if node.style == "'": return "'"+node.value.replace("'", "''")+"'"
    return node.value


def _scalar(loader, node):
    if node.tag == 'tag:yaml.org,2002:timestamp':
        try: return loader.construct_yaml_timestamp(node)
        except (AttributeError, ValueError): raise _DocumentFailure('TAG_RESOLVE_FAILED', node.start_mark) from None
    if node.tag == 'tag:yaml.org,2002:binary':
        raw = re.sub(r'[^A-Za-z0-9+/=_-]', '', node.value).replace('-', '+').replace('_', '/').split('=')[0]
        raw = raw[:len(raw)-1] if len(raw)%4 == 1 else raw
        return base64.b64decode(raw+'='*((-len(raw))%4))
    if node.tag in ('tag:yaml.org,2002:null', 'tag:yaml.org,2002:bool', 'tag:yaml.org,2002:int', 'tag:yaml.org,2002:float'):
        if loader.resolve(yaml.ScalarNode, node.value, (True, False)) != node.tag: return node.value
    if node.tag == 'tag:yaml.org,2002:null': return None
    if node.tag == 'tag:yaml.org,2002:bool': return loader.construct_yaml_bool(node)
    if node.tag == 'tag:yaml.org,2002:int': return _integer(loader, node)
    if node.tag == 'tag:yaml.org,2002:float': return loader.construct_yaml_float(node)
    return node.value


def _validate_keys(loader, node):
    if isinstance(node, _Alias): return
    if isinstance(node, yaml.SequenceNode):
        for child in node.value: _validate_keys(loader, child)
    if isinstance(node, yaml.MappingNode):
        seen = set()
        for key, value in node.value:
            if isinstance(key, yaml.ScalarNode):
                scalar = _scalar(loader, key)
                kind = 'number' if isinstance(scalar, (int, float)) and not isinstance(scalar, bool) else type(scalar)
                identity = (kind, scalar)
                if identity in seen: raise _DocumentFailure('DUPLICATE_KEY', key.start_mark)
                seen.add(identity)
            _validate_keys(loader, key); _validate_keys(loader, value)


def _to_values(loader, root):
    anchors = {}; cache = {}
    def cost(node):
        if isinstance(node, _Alias):
            state = anchors.get(id(node.value))
            return state['count']*state['cost'] if state is not None else 0
        if isinstance(node, yaml.SequenceNode): return max([cost(item) for item in node.value] or [0])
        if isinstance(node, yaml.MappingNode): return max([max(cost(key), cost(value)) for key, value in node.value] or [0])
        return 1
    def convert(node):
        if isinstance(node, _Alias):
            if node.value is None:
                raise ValueError('Unresolved alias (the anchor must be set before the alias): '+node.source_name)
            state = anchors[id(node.value)]
            state['count'] += 1
            if state['cost'] == 0: state['cost'] = cost(node.value)
            if state['count']*state['cost'] > 100:
                raise ValueError('Excessive alias count indicates a resource exhaustion attack')
            return cache[id(node.value)]
        identity = id(node)
        if identity in cache: return cache[identity]
        if getattr(node, 'dsh_anchor', None) is not None: anchors[identity] = dict(count=1, cost=0)
        if isinstance(node, yaml.ScalarNode):
            result = _scalar(loader, node); cache[identity] = result; return result
        if isinstance(node, yaml.SequenceNode):
            result = []; cache[identity] = result
            result.extend(convert(item) for item in node.value)
            return result
        result = {}; cache[identity] = result
        for key_node, value_node in node.value:
            key = convert(key_node)
            if key is None: name = ''
            elif isinstance(key, str): name = key
            elif isinstance(key, bool): name = 'true' if key else 'false'
            elif isinstance(key, (int, float)): name = js_to_string(key)
            else: name = _flow_key(key_node)
            result[name] = convert(value_node)
        return result
    return None if root is None else convert(root)


def load_document(text, filename):
    loader = DocumentLoader(text)
    try:
        root = loader.get_single_node()
        if root is not None: _validate_keys(loader, root)
        return _to_values(loader, root)
    except (_DocumentFailure, yaml.YAMLError) as error:
        mark = getattr(error, 'mark', None) or getattr(error, 'problem_mark', None)
        code = getattr(error, 'code', None) or 'YAML_PARSE_ERROR'
        where = '' if mark is None else ' at line '+str(mark.line+1)+', column '+str(mark.column+1)
        raise ValueError('credentials-local: invalid document at '+filename+': '+code+where) from None
    finally: loader.dispose()


def _section(value, name, filename):
    if value is None: return {}
    if not isinstance(value, dict):
        raise TypeError('credentials-local: "'+name+'" in '+filename+' must be a mapping')
    return value


def _fields(key, fields, allowed, filename):
    for field in _js_own_enumerable_keys(fields):
        if field not in allowed:
            raise ValueError('credentials-local: record "'+key+'" in '+filename+' has unknown field "'+field+'"')


def parse_record(key, value, filename):
    if not isinstance(value, dict):
        raise TypeError('credentials-local: record "'+key+'" in '+filename+' must be a mapping')
    kind = value.get('kind')
    if kind == 'api-key':
        _fields(key, value, ('kind', 'key', 'env'), filename)
        result = dict(kind='api-key')
        if 'key' in value:
            raw = value['key']
            if not isinstance(raw, str) or len(raw) == 0:
                raise TypeError('credentials-local: record "'+key+'" in '+filename+' has a non-string or empty key')
            result['key'] = raw
        if 'env' in value:
            raw = value['env']
            if not isinstance(raw, dict):
                raise TypeError('credentials-local: record "'+key+'" in '+filename+' has a non-mapping env')
            env = {}
            for name in _js_own_enumerable_keys(raw):
                credential_ref(name)
                if not isinstance(raw[name], str) or len(raw[name]) == 0:
                    raise TypeError('credentials-local: record "'+key+'" env "'+name+'" in '+filename+' must be a non-empty string')
                env[name] = raw[name]
            result['env'] = env
        return result
    if kind == 'grant':
        _fields(key, value, ('kind', 'payload'), filename)
        if 'payload' not in value:
            raise ValueError('credentials-local: record "'+key+'" in '+filename+' has no payload')
        assert_json_value('record "'+key+'" payload in '+filename, value['payload'])
        return dict(kind='grant', payload=value['payload'])
    if 'kind' not in value:
        raise ValueError('credentials-local: record "'+key+'" in '+filename+' has no kind')
    raise ValueError('credentials-local: record "'+key+'" in '+filename+' has unknown kind '+stringify_json(kind))


def parse_credentials_document(text, filename):
    root = load_document(text, filename)
    if root is None: root = {}
    if not isinstance(root, dict):
        raise TypeError('credentials-local: '+filename+' must be a mapping')
    keys = _js_own_enumerable_keys(root)
    if not keys: return dict(refs={}, records={}, ignoredKeys=[])
    if 'version' not in root:
        count = str(len(keys))+' '+('entry' if len(keys) == 1 else 'entries')
        raise ValueError('credentials-local: '+filename+' uses the pre-release flat layout. Add `version: 1`'
                         +' and nest the existing '+count+' under `refs:`. No values need to change.')
    version = root['version']
    if not isinstance(version, (int, float)) or isinstance(version, bool) or version != 1:
        raise ValueError('credentials-local: '+filename+' declares version '+stringify_json(version)+'; this build reads version 1')
    refs = {}
    section = _section(root.get('refs'), 'refs', filename)
    for key in _js_own_enumerable_keys(section):
        credential_ref(key)
        value = section[key]
        if not isinstance(value, str):
            raise TypeError('credentials-local: the value for "'+key+'" in '+filename+' must be a string')
        if len(value) == 0:
            raise ValueError('credentials-local: the value for "'+key+'" in '+filename+' is empty; remove the key instead')
        refs[key] = value
    records = {}
    section = _section(root.get('records'), 'records', filename)
    for key in _js_own_enumerable_keys(section):
        parse_credential_key(key)
        records[key] = parse_record(key, section[key], filename)
    return dict(refs=refs, records=records, ignoredKeys=[key for key in keys if key not in ('version', 'refs', 'records')])
