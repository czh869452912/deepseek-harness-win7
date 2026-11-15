import ast
import unicodedata

import pytest

from dsh.core.ptc_sdk import render_tools_sdk_py
from scripts.rc022_ptc_sdk_probe import observe


@pytest.mark.asyncio
async def test_sdk_schema_shapes_escapes_and_deep_declarations_parse():
    rows = await observe()
    text = rows[19]['value']
    assert 'class ReadArgsOptions(TypedDict)' in text
    assert 'path: str' in text
    assert 'NotRequired[ReadArgsOptions]' in text
    assert '-> ReadOutput:' in text
    assert '\\x00' in text and '\\ud800' in text


def test_sdk_uses_target_interpreter_unicode_tables_at_all_identifier_sites():
    # These characters were added after Python 3.8's Unicode 12.1 tables;
    # Node24 accepting them must not make the worker's prompt unparseable.
    names = ['zz-\U0001e4d0x', '\u019b', 'a\u200cb', '\U00010570']
    schemas = [dict(name=name, parameters={'type': 'object', 'properties': {
        name: {'type': 'object', 'additionalProperties': False}}}, output={}) for name in names]
    text = render_tools_sdk_py(schemas)
    code = text.split('```python\n', 1)[1].rsplit('\n```', 1)[0]
    compile(code, '<PTC SDK>', 'exec')
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef)):
            assert unicodedata.normalize('NFKC', node.name) == node.name
    assert '\uA7DC' not in text


def test_sdk_caps_lists_for_python38_parser_in_parameters_and_optional_fields():
    schema = {'type': 'string', 'enum': ['x']}
    for _ in range(240):
        schema = {'type': 'array', 'items': schema}
    text = render_tools_sdk_py([dict(name='deep', parameters=schema, output={
        'type': 'object', 'properties': {'field': schema}})])
    code = text.split('```python\n', 1)[1].rsplit('\n```', 1)[0]
    compile(code, '<PTC SDK>', 'exec')
    assert 'list[' * 80 + 'Any' in code
    assert 'NotRequired[' + 'list[' * 79 + 'Any' in code
