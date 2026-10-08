"""Complete selected route values with explicit allocated identity graphs."""
import copy
import json
import re

uuid_pattern = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')


def installation(checkout):
    return ('The DeepSeek Harness implementation checkout is at ' + checkout + '. '
        'The checkout location and current working directory are separate values and may differ; '
        'never infer the working directory from this path. Use pwd to determine the current working directory. '
        'Use this checkout only to inspect or extend DSH itself.')


def project(report, checkout):
    assert not report.get('failure') and report['exitCode'] == 0
    assert report['observedClock'] == 1791244800000
    rows = copy.deepcopy(report['rows'])
    assert [row['name'] for row in rows] == ['SPAWN_INHERIT', 'SPAWN_CHANGE', 'SPAWN_EFFORT',
        'DENIED_ROUTE', 'HALF_ROUTE', 'FORK_INHERIT', 'CANCEL']
    for row in rows:
        parent = row['parentHeader']['id']
        assert parent == 'route-parent-' + row['name'].lower() and row['parentStatus'] == 'idle'
        agents = row['public']['created']
        assert len(agents) == (1 if row['name'] in ('DENIED_ROUTE', 'HALF_ROUTE') else 2)
        children = {agent['id']: row['name'] + '/allocated-child' for agent in agents if agent['id'] != parent}
        assert all(uuid_pattern.fullmatch(identity) for identity in children)
        messages = {}
        for event in row['public']['events']:
            body = event['event']['data']
            if event['event']['type'] == 'user/message':
                message = body
            elif event['event']['type'] in ('assistant/message', 'tool/result'):
                message = body['message']
            else:
                continue
            identity = message['id']
            assert uuid_pattern.fullmatch(identity)
            if identity not in messages:
                messages[identity] = row['name'] + '/allocated-message/' + str(len(messages))

        def walk(value, path):
            if isinstance(value, list):
                if path and path[-1] == 'disposed':
                    assert all(identity in children for identity in value)
                    return [children[identity] for identity in value]
                return [walk(item, path + [position]) for position, item in enumerate(value)]
            if not isinstance(value, dict):
                return value
            result = {}
            for key, content in value.items():
                current = path + [key]
                if key == 'id' and isinstance(content, str) and content in messages and value.get('role') in ('user', 'assistant', 'tool'):
                    result[key] = messages[content]
                elif key in ('sessionId', 'runId', 'subagentId', 'parentSession', 'id') and isinstance(content, str) and content in children:
                    assert key != 'id' or ('version' in value and 'createdAt' in value or 'header' in value and 'options' in value)
                    result[key] = children[content]
                elif key == 'system' and isinstance(content, str):
                    expected = installation(checkout)
                    assert content.count(expected) == 1
                    result[key] = content.replace(expected, installation('<verified producer installation>'))
                elif key == 'text' and isinstance(content, str) and content.startswith('{"kind":"foreground",'):
                    payload = json.loads(content)
                    assert payload['kind'] == 'foreground' and payload['runId'] in children
                    result[key] = json.dumps(walk(payload, current + ['foreground-output']), separators=(',', ':'), ensure_ascii=False)
                else:
                    result[key] = walk(content, current)
            return result

        row.update(walk(row, []))
    return rows
