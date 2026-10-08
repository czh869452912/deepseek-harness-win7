"""Complete actual workflow/Ralph child compositions with declared allocation identities."""
import copy
import json
from pathlib import Path
import re

work = Path(__file__).resolve().parent
uuid = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')

def installation(checkout):
    return ('The DeepSeek Harness implementation checkout is at ' + checkout + '. '
        'The checkout location and current working directory are separate values and may differ; '
        'never infer the working directory from this path. Use pwd to determine the current working directory. '
        'Use this checkout only to inspect or extend DSH itself.')

def project(report, checkout):
    assert not report.get('failure') and report['exitCode'] == 0 and report['observedClock'] == 1791244800000
    rows = copy.deepcopy(report['rows'])
    assert [row['name'] for row in rows] == ['WORKFLOW_MODEL', 'WORKFLOW_CANCEL', 'RALPH_ROUNDS']
    for row in rows:
        parent = 'route-parent-' + row['name'].lower()
        assert row['parentHeader']['id'] == parent and row['parentStatus'] == 'idle'
        agents = row['public']['created']
        assert len(agents) == (3 if row['name'] == 'RALPH_ROUNDS' else 2)
        assert agents[0]['id'] == parent
        children = {agent['id']: row['name'] + '/allocated-child/' + str(index) for index,agent in enumerate(agents[1:])}
        assert all(uuid.fullmatch(name) for name in children)
        messages, workflows = {}, {}
        for event in row['public']['events']:
            kind, body = event['event']['type'], event['event']['data']
            if kind == 'tool-workflow/run-start':
                name = body['runId']
                assert uuid.fullmatch(name) and name not in workflows
                workflows[name] = row['name'] + '/allocated-workflow/' + str(len(workflows))
            if kind == 'user/message':
                message = body
            elif kind in ('assistant/message', 'tool/result'):
                message = body['message']
            else:
                continue
            assert uuid.fullmatch(message['id'])
            if message['id'] not in messages:
                messages[message['id']] = row['name'] + '/allocated-message/' + str(len(messages))
        assert len(workflows) == (0 if row['name'] == 'RALPH_ROUNDS' else 1)
        assert len(row['public']['disposed']) == len(children)

        def walk(value, path):
            if isinstance(value, list):
                if path and path[-1] == 'disposed':
                    assert all(name in children for name in value)
                    return [children[name] for name in value]
                return [walk(item,path+[position]) for position,item in enumerate(value)]
            if not isinstance(value, dict):
                return value
            result = {}
            for name,item in value.items():
                current = path + [name]
                if name == 'id' and isinstance(item,str) and item in messages and value.get('role') in ('user','assistant','tool'):
                    result[name] = messages[item]
                elif name in ('sessionId','runId','subagentId','parentSession','childId','id') and isinstance(item,str) and item in children:
                    assert name != 'id' or ('version' in value and 'createdAt' in value or 'header' in value and 'options' in value)
                    result[name] = children[item]
                elif name == 'runId' and isinstance(item,str) and item in workflows:
                    result[name] = workflows[item]
                elif name == 'system' and isinstance(item,str):
                    expected = installation(checkout)
                    assert item.count(expected) == 1
                    result[name] = item.replace(expected,installation('<verified producer installation>'))
                else:
                    result[name] = walk(item,current)
            return result
        row.update(walk(row, []))
    return rows
