import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from dsh.mcp.schemas import DEFINITIONS, SchemaError, parse


ROOT = Path(__file__).resolve().parents[1]


def test_pinned_mcp_schemas_preserve_all_raw_source_parse_observations(tmp_path):
    sdk = Path(os.environ.get('MCP_SCHEMA_SDK', str(ROOT / 'scripts/oracles/official/node_modules/@modelcontextprotocol/sdk')))
    node = shutil.which('node')
    assert node and sdk.exists(), 'source SDK schema observer requires the pinned developer SDK'
    exported, observations = tmp_path / 'schema.json', tmp_path / 'observations.json'
    subprocess.run([node, str(ROOT / 'scripts/oracles/mcp_schema_export.mjs'), str(sdk), str(exported)], check=True)
    assert json.loads(exported.read_text(encoding='utf-8')) == DEFINITIONS
    subprocess.run([node, str(ROOT / 'scripts/oracles/mcp_schema_probe.mjs'), str(sdk), str(exported), str(observations)], check=True)
    rows = json.loads(observations.read_text(encoding='utf-8'))
    assert len(rows) == 962
    for row in rows:
        try:
            result = {'data': parse(row['name'], row['value'])}
        except SchemaError as error:
            result = {'issues': error.issues, 'message': error.message}
        assert result == row['result'], (row['name'], row['label'])


@pytest.mark.parametrize('value', [[], {}, {'1': []}])
def test_assert_object_accepts_source_arrays_and_records(value):
    parsed = parse('InitializeResultSchema', {'protocolVersion': '2025-11-25',
        'serverInfo': {'name': 'server', 'version': '1', 'extra': 'stripped'},
        'capabilities': {'logging': value, 'experimental': {'controlled': value}}, 'extra': 'retained'})
    assert parsed['capabilities']['logging'] == value
    assert parsed['capabilities']['experimental']['controlled'] == value
    assert parsed['serverInfo'] == {'name': 'server', 'version': '1'}
    assert parsed['extra'] == 'retained'


def test_invalid_annotations_preserve_sdk_issues_before_consumer_registration():
    with pytest.raises(SchemaError) as failure:
        parse('ListToolsResultSchema', {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}, 'annotations': False}]})
    assert failure.value.issues == [{'expected': 'object', 'code': 'invalid_type', 'path': ['tools', 0, 'annotations'],
        'message': 'Invalid input: expected object, received boolean'}]


def test_tool_projection_strips_only_sdk_owned_unknown_fields():
    tool = {'name': 'echo', 'inputSchema': {'type': 'object', 'properties': {'value': []}, 'extension': 1}, 'unknown': 1}
    assert parse('ListToolsResultSchema', {'tools': [tool], 'extension': 2}) == {
        'tools': [{'name': 'echo', 'inputSchema': {'type': 'object', 'properties': {'value': []}, 'extension': 1}}], 'extension': 2}
