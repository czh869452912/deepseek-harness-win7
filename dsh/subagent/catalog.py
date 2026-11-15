"""v4 Session catalog: legacy v0-v2 facts plus named v3 children.

The older active composition still imports catalog_current until its C6/C9
consumers switch together. This definition requires stateVersion 6 checkpoints.
"""
import math
import time
from dsh.subagent.catalog_current import append_chunk, iterate_chunks
from dsh.subagent.names import is_agent_name

SUBAGENT_CATALOG_VERSION = 3


def integer(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0 and value == int(value) and value <= 9007199254740991


def fact(value):
    if not isinstance(value, dict):
        raise ValueError('invalid subagent catalog fact')
    version, mode = value.get('version'), value.get('mode')
    if type(version) not in (int, float) or (version, mode) not in (
            (0, 'one-shot'), (0, 'continuable'), (1, 'one-shot'), (1, 'continuable'),
            (1, 'unknown'), (2, 'external'), (3, 'continuable'), (3, 'external')):
        raise ValueError('invalid subagent catalog version/mode')
    allowed = {'version', 'childId', 'childCreatedAt', 'mode', 'label'}
    if version == 3: allowed.add('name')
    if (set(value)-allowed or not isinstance(value.get('childId'), str)
            or not integer(value.get('childCreatedAt'))
            or (mode == 'continuable' or 'label' in value) and not isinstance(value.get('label'), str)
            or version == 3 and not is_agent_name(value.get('name'))):
        raise ValueError('invalid subagent catalog fact')
    return dict(value)


def parse_state(value):
    if not isinstance(value, dict) or set(value)-{'inheritedEventCount', 'head'} or not integer(value.get('inheritedEventCount')):
        raise ValueError('invalid subagent catalog state')
    result = dict(inheritedEventCount=value['inheritedEventCount'])
    target, node, seen = result, value.get('head'), set()
    while node is not None:
        if (not isinstance(node, dict) or id(node) in seen or set(node)-{'values', 'previous'}
                or not isinstance(node.get('values'), list) or not 1 <= len(node['values']) <= 64):
            raise ValueError('invalid subagent catalog chunk')
        seen.add(id(node))
        parsed = dict(values=[fact(item) for item in node['values']])
        target['head' if target is result else 'previous'] = parsed
        target = parsed
        if 'previous' in node and node['previous'] is None:
            raise ValueError('invalid subagent catalog chunk')
        node = node.get('previous')
    if 'head' in value and value['head'] is None:
        raise ValueError('invalid subagent catalog chunk')
    return result


def apply(state, event):
    if event['type'] != 'subagent/catalog' or event['seq'] < state['inheritedEventCount']:
        return state
    return dict(state, head=append_chunk(state.get('head'), fact(event['data'])))


def view(state):
    return [dict(id=data['childId'], createdAt=data['childCreatedAt'],
                 **{key: value for key, value in data.items() if key not in ('version', 'childId', 'childCreatedAt')})
            for data in iterate_chunks(state.get('head'))]


def parse_view(value):
    if not isinstance(value, list):
        raise ValueError('invalid subagent catalog view')
    rows = []
    for row in value:
        if not isinstance(row, dict) or set(row)-{'id', 'createdAt', 'mode', 'label', 'name'}:
            raise ValueError('invalid subagent catalog row')
        mode = row.get('mode')
        version = (3 if 'name' in row else 2 if mode == 'external' else 1 if mode == 'unknown' else 0)
        data = fact(dict(version=version, childId=row.get('id'), childCreatedAt=row.get('createdAt'),
            **{key: value for key, value in row.items() if key not in ('id', 'createdAt')}))
        rows.append(dict(id=data.pop('childId'), createdAt=data.pop('childCreatedAt'),
                         **{key: value for key, value in data.items() if key != 'version'}))
    return rows


CATALOG = dict(key='subagentCatalog', stateVersion=6, stateSchema=parse_state,
    init=lambda header, cut: dict(inheritedEventCount=cut), apply=apply,
    wire=dict(viewSchema=parse_view, view=view))


def establish_catalog_child(parent, child, descriptor, name):
    identity = child['id'] if isinstance(child, dict) else child.id
    created = child['createdAt'] if isinstance(child, dict) else child.createdAt
    parent.append('subagent/catalog', dict(version=SUBAGENT_CATALOG_VERSION,
        childId=identity, childCreatedAt=created, mode=descriptor['mode'], label=descriptor['label'], name=name))


def establish_external_catalog_child(parent, child_id, label, name):
    parent.append('subagent/catalog', dict(version=SUBAGENT_CATALOG_VERSION,
        childId=child_id, childCreatedAt=int(time.time()*1000), mode='external', label=label, name=name))


def catalog_names(entries):
    return {entry['name'] for entry in entries if 'name' in entry}


subagentCatalogProjectionDefinition = CATALOG
establishCatalogChild = establish_catalog_child
establishExternalCatalogChild = establish_external_catalog_child
catalogNames = catalog_names
