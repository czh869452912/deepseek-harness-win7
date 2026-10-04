import math

from dsh.cordis.json_text import normalize_json_string, stringify_json
from dsh.cordis.utils import _js_number_to_string, _js_own_enumerable_keys
from dsh.session.session_query import extract_session_event_text
from dsh.session.tool_query_workspace import title_text, visit_descendants


def number_text(value):
    return _js_number_to_string(value)


def format_time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 8640000000000000:
        raise ValueError('Invalid time value')
    days, remainder = divmod(int(value), 86400000)
    shifted_days = days + 719468
    era = shifted_days // 146097
    day_of_era = shifted_days - era * 146097
    year_of_era = (day_of_era - day_of_era // 1460 + day_of_era // 36524 - day_of_era // 146096) // 365
    year = year_of_era + era * 400
    day_of_year = day_of_era - (365 * year_of_era + year_of_era // 4 - year_of_era // 100)
    month_prime = (5 * day_of_year + 2) // 153
    day = day_of_year - (153 * month_prime + 2) // 5 + 1
    month = month_prime + (3 if month_prime < 10 else -9)
    year += month <= 2
    hour, remainder = divmod(remainder, 3600000)
    minute, remainder = divmod(remainder, 60000)
    second, millisecond = divmod(remainder, 1000)
    year_text = '{:04d}'.format(year) if 0 <= year <= 9999 else ('+' if year >= 0 else '-') + '{:06d}'.format(abs(year))
    return '{}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:03d}Z'.format(year_text, month, day, hour, minute, second, millisecond)


def pretty_json(value):
    output = []
    pending = [('value', value, 0)]
    while pending:
        kind, current, depth = pending.pop()
        if kind == 'text':
            output.append(current)
            continue
        if isinstance(current, dict):
            normalized = {normalize_json_string(key): child for key, child in current.items()}
            entries = [(key, normalized[key]) for key in _js_own_enumerable_keys(normalized)]
            if not entries:
                output.append('{}')
                continue
            output.append('{\n')
            pending.append(('text', '\n' + '  ' * depth + '}', depth))
            for index in range(len(entries) - 1, -1, -1):
                key, child = entries[index]
                if index != len(entries) - 1:
                    pending.append(('text', ',\n', depth))
                pending.append(('value', child, depth + 1))
                pending.append(('text', '  ' * (depth + 1) + stringify_json(key) + ': ', depth))
        elif isinstance(current, list):
            if not current:
                output.append('[]')
                continue
            output.append('[\n')
            pending.append(('text', '\n' + '  ' * depth + ']', depth))
            for index in range(len(current) - 1, -1, -1):
                if index != len(current) - 1:
                    pending.append(('text', ',\n', depth))
                pending.append(('value', current[index], depth + 1))
                pending.append(('text', '  ' * (depth + 1), depth))
        else:
            output.append(stringify_json(current))
    return ''.join(output)


def availability_text(record):
    return ', '.join(name for name in ('live', 'persisted') if record.get(name)) or 'unavailable'


def seq_list(values):
    return ', '.join(number_text(value) for value in values) if values else 'none'


def format_empty_session_search():
    return 'No prior session matches found.'


def format_session_search(collected, titles, authorized_parents):
    if not collected['items']:
        return format_empty_session_search()
    lines = ['Session search results ({}):'.format(len(collected['items']))]
    for index, hit in enumerate(collected['items']):
        header, match = hit['header'], hit['bestMatch']
        parent = 'root' if 'parentSession' not in header else header['parentSession'] if header['parentSession'] in authorized_parents else '[outside workspace]'
        lines.extend(['', '{}. Session {} — {}'.format(index + 1, header['id'], title_text(titles.get(header['id']))),
                      '   Created: ' + format_time(header['createdAt']), '   Parent: ' + parent,
                      '   Availability: ' + availability_text(hit),
                      '   Best match: seq {} | {} | {} | {}'.format(number_text(match['seq']), match['type'], match['surface'], format_time(match['time'])),
                      '   Snippet: ' + match['snippet']])
    if collected['capped']:
        lines.extend(['', 'Result cap reached. Narrow the query or add filters to find additional matches.'])
    return '\n'.join(lines)


def format_event_search(session_id, title, collected):
    lines = ['Session {} — {}'.format(session_id, title_text(title))]
    if not collected['items']:
        return '\n'.join(lines + ['', 'No prior event matches found.'])
    lines.extend(['', 'Event search results ({}):'.format(len(collected['items']))])
    for index, hit in enumerate(collected['items']):
        lines.extend(['{}. seq {} | {} | {} | {}'.format(index + 1, number_text(hit['seq']), hit['type'], hit['surface'], format_time(hit['time'])),
                      '   Snippet: ' + hit['snippet']])
    if collected['capped']:
        lines.extend(['', 'Result cap reached. Narrow the query or add filters to find additional matches.'])
    return '\n'.join(lines)


def format_session_trace(trace, ancestors, ancestor_boundary, descendants, titles):
    target = trace['target']
    lines = ['Session {} — {}'.format(target['header']['id'], title_text(titles.get(target['header']['id']))),
             'Created: ' + format_time(target['header']['createdAt']), 'Availability: ' + availability_text(target),
             '', 'Ancestors (nearest first):']
    if not ancestors and not ancestor_boundary:
        lines.append('- none (target is a root session)')
    for record in ancestors:
        header = record['header']
        lines.append('- {} — {} | {} | {}'.format(header['id'], title_text(titles.get(header['id'])), format_time(header['createdAt']), availability_text(record)))
    if ancestor_boundary:
        lines.append('- [outside workspace boundary]')
    lines.extend(['', 'Descendants:'])
    if not descendants:
        lines.append('- none')
    for node, depth in visit_descendants(descendants):
        indent = '  ' * depth
        if node is None:
            lines.append(indent + '- [outside workspace subtree]')
            continue
        record = node['record']
        header = record['header']
        lines.append(indent + '- {} — {} | {} | {}'.format(header['id'], title_text(titles.get(header['id'])), format_time(header['createdAt']), availability_text(record)))
    return '\n'.join(lines)


def format_event_trace(session_id, title, trace):
    target = trace['target']
    lines = ['Session {} — {}'.format(session_id, title_text(title)),
             'Target: seq {} | {} | {} | {}'.format(number_text(target['seq']), target['type'], target['surface'], format_time(target['time'])),
             'Replaced by: ' + (number_text(trace['replacedBy']) if trace.get('replacedBy') is not None else 'none')]
    for label, field in [('Replacement chain', 'replacementChain'), ('Events replaced by target', 'replacedEventSeqs'),
                         ('Events cited directly as sources', 'sourceEventSeqs'), ('Direct derived events', 'derivedEventSeqs')]:
        lines.append(label + ': ' + seq_list(trace[field]))
    return '\n'.join(lines)


def format_neighbor(event):
    text = extract_session_event_text(event)
    return '- seq {} | {} | {}'.format(number_text(event['seq']), event['type'], format_time(event['time'])) + (
        '\n  ' + text.replace('\n', '\n  ') if text else ' | (no semantic text)')


def format_event_read(session_id, title, window):
    target = window['target']
    before = [event for event in window['events'] if event['seq'] < target['seq']]
    after = [event for event in window['events'] if event['seq'] > target['seq']]
    lines = ['Session {} — {}'.format(session_id, title_text(title)), 'Target event seq {}:'.format(number_text(target['seq'])),
             '```json', pretty_json(target), '```']
    for label, events in [('Before', before), ('After', after)]:
        if events:
            lines.extend(['', label + ':'])
            lines.extend(format_neighbor(event) for event in events)
    return '\n'.join(lines)


def present_search_call(session_search, args):
    return dict(card='generic', kind='search', title='Search prior sessions' if session_search else 'Search session events', rawInput=args['query'])


def present_session_trace_call(args):
    result = dict(card='generic', kind='read', title='Trace current session' if 'session_id' not in args else 'Trace session ' + args['session_id'])
    if 'session_id' in args:
        result['rawInput'] = args['session_id']
    return result


def present_event_target_call(action, args):
    raw = {name: args[name] for name in ('session_id', 'seq') if name in args}
    return dict(card='generic', kind='read', title=action + ' ' + number_text(args['seq']), rawInput=raw)
