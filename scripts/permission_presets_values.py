import copy
import hashlib
import json

from scripts.canonical_llm_values import observation_digest as value_digest


NAMES = ('settings-labels', 'initial-projection') + tuple('state-%s' % index for index in range(10)) + tuple(
    'view-%s' % index for index in range(9)) + tuple('command-%s' % index for index in range(5)) + (
    'live-default', 'future-default', 'settings-detach', 'permission-unload')
REFUSALS = ('state-2', 'state-3', 'state-4', 'state-5', 'state-6', 'state-7', 'state-8',
    'view-3', 'view-4', 'view-5', 'view-6', 'view-7', 'view-8')
DOMAIN_NAMES = ('fresh', 'mount-existing', 'inferred-danger', 'explicit-danger-default', 'selected-only',
    'sandbox-only', 'approval-only', 'seed-empty', 'seed-historical', 'seed-custom', 'set-danger', 'set-noop',
    'set-alias', 'stale-alias', 'custom-view', 'unknown-set', 'reserved-table', 'unconfined',
    'unmatched-default', 'unknown-default', 'empty-description', 'empty-key', 'numeric-first',
    'numeric-selected', 'numeric-boundary')
OBSERVED_CLOCK = 1791283200000
GROUPS = ('lifecycle', 'domain')
ALL_NAMES = tuple('lifecycle/' + name for name in NAMES) + tuple('domain/' + name for name in DOMAIN_NAMES)


def schema_graph(graph):
    if not isinstance(graph, dict) or set(graph) != {'uid', 'refs'} or type(graph['uid']) is not int or not isinstance(graph['refs'], dict):
        raise ValueError('Permission Schema graph shape differs')
    if any(not isinstance(key, str) or not key.isascii() or not key.isdecimal() or str(int(key)) != key for key in graph['refs']):
        raise ValueError('Permission Schema allocated reference shape differs')
    identities, converted = {}, {}

    def reference(identity):
        if type(identity) is not int or identity < 0 or str(identity) not in graph['refs']:
            raise ValueError('Permission Schema reference missing')
        if identity in identities:
            return identities[identity]
        token = len(identities)
        identities[identity] = token
        node = copy.deepcopy(graph['refs'][str(identity)])
        if not isinstance(node, dict):
            raise ValueError('Permission Schema node missing')
        if node.get('type') == 'object':
            if not isinstance(node.get('dict'), dict):
                raise ValueError('Permission Schema object members missing')
            node['dict'] = {key: reference(value) for key, value in node['dict'].items()}
        elif node.get('type') == 'union':
            if not isinstance(node.get('list'), list):
                raise ValueError('Permission Schema union choices missing')
            node['list'] = [reference(value) for value in node['list']]
        elif node.get('type') != 'const':
            raise ValueError('Unobserved Permission Schema node type')
        converted[str(token)] = node
        return token

    selected = reference(graph['uid'])
    if len(identities) != len(graph['refs']):
        raise ValueError('Permission Schema unreachable references')
    return dict(uid=selected, refs=converted)


def observation_digest(report, side):
    rows = report.get('rows')
    if not isinstance(rows, list) or len(rows) != len(NAMES) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Permission lifecycle complete rows missing')
    if tuple(row.get('name') for row in rows) != NAMES:
        raise ValueError('Permission lifecycle row order or identity differs')
    if tuple(row['name'] for row in rows if row.get('refused') is True) != REFUSALS:
        raise ValueError('Permission lifecycle exact refusal decisions differ')
    raw_errors = report.get('rawErrors')
    if not isinstance(raw_errors, list) or tuple(row.get('name') for row in raw_errors if isinstance(row, dict)) != REFUSALS:
        raise ValueError('Permission lifecycle raw validation errors missing')
    for raw in raw_errors:
        error = raw.get('error')
        if not isinstance(error, dict) or not isinstance(error.get('message'), str) or not error['message']:
            raise ValueError('Permission lifecycle raw validation diagnostics missing')
        if error.get('name') != ('ZodError' if side == 'source' else 'ValueError'):
            raise ValueError('Permission lifecycle validation error carrier differs')
        if side == 'source' and (not isinstance(error.get('issues'), list) or not error['issues']):
            raise ValueError('Permission lifecycle original validation issues missing')
    normalized = copy.deepcopy(rows)
    original_schema = None
    for row in normalized:
        if row['name'] in ('settings-labels', 'live-default'):
            descriptors = row.get('descriptors', row.get('value'))
            if not isinstance(descriptors, list) or len(descriptors) != 1:
                raise ValueError('Permission settings descriptor missing')
            for descriptor in descriptors:
                if original_schema is None:
                    original_schema = copy.deepcopy(descriptor['schema'])
                elif descriptor['schema'] != original_schema:
                    raise ValueError('Permission live settings replaced the original schema identity or graph')
                descriptor['schema'] = schema_graph(descriptor['schema'])
    return value_digest([dict(name='permission-lifecycle', group='retry', rows=normalized)], side=side)


def domain_digest(report, side):
    rows = report.get('rows')
    if report.get('observedClock') != OBSERVED_CLOCK:
        raise ValueError('Permission domain controlled clock differs')
    if not isinstance(rows, list) or len(rows) != len(DOMAIN_NAMES) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Permission complete domain rows missing')
    if tuple(row.get('name') for row in rows) != DOMAIN_NAMES:
        raise ValueError('Permission domain row order or identity differs')
    for row in rows:
        if not isinstance(row.get('rawEvents'), list) or not isinstance(row.get('trace'), list):
            raise ValueError('Permission domain raw events missing')
        for event in row['rawEvents']:
            if not isinstance(event, dict) or type(event.get('time')) is not int or event['time'] != OBSERVED_CLOCK:
                raise ValueError('Permission domain raw event clock differs')
        if 'error' in row:
            if set(row['error']) != {'name', 'message'} or row['error']['name'] != 'Error' or not isinstance(row['error']['message'], str):
                raise ValueError('Permission domain error carrier differs')
        elif not isinstance(row.get('result'), dict):
            raise ValueError('Permission domain business outcome missing')
    return value_digest([dict(name='permission-domain', group='retry', rows=rows)], side=side)


def complete_digest(report, side):
    groups = report.get('groups')
    if not isinstance(groups, dict) or set(groups) != set(GROUPS):
        raise ValueError('Permission complete child groups missing')
    for group in GROUPS:
        if not isinstance(groups[group], dict):
            raise ValueError('Permission child observations missing')
    hashes = [observation_digest(groups['lifecycle'], side), domain_digest(groups['domain'], side)]
    return hashlib.sha256(json.dumps(hashes, separators=(',', ':')).encode('utf-8')).hexdigest()
