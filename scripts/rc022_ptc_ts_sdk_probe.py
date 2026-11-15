"""Pair both PTC evaluation forms' TypeScript SDK text without a Node dependency in the host."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_ptc_sdk_probe import cases as python_cases


def cases():
    data = python_cases()
    for required, command, description in ((['command'], {}, {}),
        (['command','description'], {}, {}), (['command','description','cwd'], {}, {}),
        ([], {'const':'other'}, {}), ([], {'enum':['pwd']}, {}),
        (['description'], {}, {'enum':['other']}), (['description'], {}, {'const':'Show current directory'})):
        data['sets'].append([dict(name='bash', description='Shell */ \n command', parameters=dict(type='object',
            properties=dict(command=dict(type='string', **command), description=dict(type='string', **description), cwd={}),
            required=required), output=dict(type='string'))])
    data['scalars'].append(dict(type='array', items=dict(type='string', const='|&')))
    data['scalars'].append(dict(type='array', items=dict(type='object', properties=dict(x=dict(type='string')))))
    return data


async def observe():
    from dsh.core.ptc_sdk_ts import json_schema_to_ts, render_tools_sdk
    data = cases()
    return ([dict(kind='scalar', value=json_schema_to_ts(schema)) for schema in data['scalars']]
        + [dict(kind=format, value=render_tools_sdk(schemas, format))
           for format in ('function-body','repl','script') for schemas in data['sets']])


def prepare(output):
    path = output / 'cases.json'
    path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_ptc_ts_sdk.mts', 'Byte-identical TypeScript SDK text from shared argument/output schemas: arbitrary keys, comments, open objects, union-array precedence, deep schemas and schema-qualified shell examples for function-body/repl/script. No TypeScript or Node runtime is introduced into the Python host.',
        [Path(__file__).resolve(), ROOT/'dsh/core/ptc_sdk_ts.py'], prepare)
