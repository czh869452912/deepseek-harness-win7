"""Current generated Service/Event contracts with progressive type closure."""
import json
from pathlib import Path
import re
from functools import lru_cache

from dsh.cordis.json_text import stringify_json
from dsh.core.session.json import UNDEFINED

RESOURCE = json.loads(Path(__file__).with_name('inspect_catalog_022.json').read_text(encoding='utf-8'))
SERVICE_API, EVENT_API, TYPE_API = [RESOURCE['catalogs'][key] for key in ('SERVICE_API', 'EVENT_API', 'TYPE_API')]
HOST_EVENTS = [event for event in EVENT_API if not event['name'].startswith('cordis/')]


@lru_cache(maxsize=2048)
def _pattern(name):
    return re.compile(r'\b' + name + r'\b', re.ASCII)


def _closure(seeds):
    included, frontier = set(), list(seeds)
    while frontier:
        following = []
        for entry in TYPE_API:
            if entry['name'] in included:
                continue
            # The generated upstream names are regex patterns here, exactly as
            # in its new RegExp(`\\b${entry.name}\\b`) query implementation.
            pattern = _pattern(entry['name'])
            if not any(pattern.search(text) for text in frontier):
                continue
            included.add(entry['name'])
            following.append(entry['declaration'])
        frontier = following
    return [entry for entry in TYPE_API if entry['name'] in included]


def query_service_api(key=UNDEFINED, services=None):
    services = SERVICE_API if services is None else services
    if key is UNDEFINED:
        return dict(mode='catalog', services=[dict(key=row['key'], description=row['summary'],
            methods=[dict(signature=method['signature']) for method in row['methods']]) for row in services])
    service = next((row for row in services if row['key'] == key), None)
    if service is None:
        raise ValueError('no catalogued Service named "{}"'.format(key))
    expression = 'ctx.' + key if re.fullmatch(r'[A-Za-z_$][\w$]*', key, re.ASCII) else 'ctx[' + stringify_json(key) + ']'
    return dict(mode='service', service=dict(key=key, description=service['description'], access=dict(
        optional=dict(expression='ctx.get(' + stringify_json(key) + ')', requiresUndefinedCheck=True),
        hardDependency=dict(inject=[key], expression=expression)), methods=service['methods']),
        referencedTypes=_closure([method['signature'] for method in service['methods']]))


def query_event_api(name=UNDEFINED, events=None):
    events = EVENT_API if events is None else events
    if name is UNDEFINED:
        return dict(mode='catalog', events=[dict(name=row['name'], description=row['summary'],
            mode=row['mode'], signature=row['signature']) for row in events])
    event = next((row for row in events if row['name'] == name), None)
    if event is None:
        raise ValueError('no catalogued Event named "{}"'.format(name))
    return dict(mode='event', event=dict(name=name, description=event['description'], mode=event['mode'],
        signature=event['signature'], parameters=event['parameters']), referencedTypes=_closure([event['signature']]))
