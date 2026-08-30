import os
import shutil
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin
from dsh.fs.fs_local import LocalFilesystemPlugin
from dsh.fs.tool_str_replace_editor import StrReplaceEditorPlugin


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix='dsh-test-editor-')
    yield d
    shutil.rmtree(d, ignore_errors=True)


async def setup_editor(temp_dir, config=None):
    ctx = Context()
    tools_plugin = ToolsPlugin()
    tools_plugin.apply(ctx)
    fs_plugin = LocalFilesystemPlugin({'cwd': temp_dir})
    fs_plugin.apply(ctx)
    editor_plugin = StrReplaceEditorPlugin(config)
    editor_plugin.apply(ctx)
    return ctx


@pytest.mark.asyncio
async def test_registers_the_standalone_schema_and_configurable_description(temp_dir):
    ctx = await setup_editor(temp_dir, {'description': 'custom editor description'})
    tools_svc = ctx.get('tools')
    schemas = tools_svc.schemas()
    assert len(schemas) >= 1
    schema = next((s for s in schemas if s['name'] == 'str_replace_editor'), None)
    assert schema is not None
    assert schema['description'] == 'custom editor description'


@pytest.mark.asyncio
async def test_creates_views_replaces_and_inserts_with_canonical_model_facing_output(temp_dir):
    ctx = await setup_editor(temp_dir)
    tools_svc = ctx.get('tools')
    sample = os.path.join(temp_dir, 'sample.txt')


    res1 = await tools_svc.execute_tool('str_replace_editor', {
        'command': 'create',
        'path': sample,
        'file_text': 'one\ntwo\nthree\n',
    })
    assert 'New file created successfully at:' in res1 and 'sample.txt' in res1

    res2 = await tools_svc.execute_tool('str_replace_editor', {
        'command': 'view',
        'path': sample,
    })
    assert '     2  two' in res2

    res3 = await tools_svc.execute_tool('str_replace_editor', {
        'command': 'view',
        'path': sample,
        'view_range': [2, -1],
    })
    assert '     2  two' in res3
    assert '     3  three' in res3

    res4 = await tools_svc.execute_tool('str_replace_editor', {
        'command': 'str_replace',
        'path': sample,
        'old_str': 'two',
        'new_str': 'TWO',
    })
    assert 'has been edited successfully.' in res4

    res5 = await tools_svc.execute_tool('str_replace_editor', {
        'command': 'insert',
        'path': sample,
        'insert_line': 1,
        'new_str': 'between',
    })
    assert 'has been edited successfully.' in res5

    with open(sample, 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'between' in content


@pytest.mark.asyncio
async def test_writes_replacement_text_literally(temp_dir):
    ctx = await setup_editor(temp_dir)
    tools_svc = ctx.get('tools')
    sample = os.path.join(temp_dir, 'literal.txt')
    replacement = "$&!$`!$'!$$"
    with open(sample, 'w', encoding='utf-8') as f:
        f.write('before OLD after')

    res = await tools_svc.execute_tool('str_replace_editor', {
        'command': 'str_replace',
        'path': sample,
        'old_str': 'OLD',
        'new_str': replacement,
    })
    assert 'edited successfully' in res
    with open(sample, 'r', encoding='utf-8') as f:
        content = f.read()
    assert content == f'before {replacement} after'


@pytest.mark.asyncio
async def test_uses_old_str_only_replacement_failures_and_rejects_relative_paths(temp_dir):
    ctx = await setup_editor(temp_dir)
    tools_svc = ctx.get('tools')
    ambiguous = os.path.join(temp_dir, 'ambiguous.txt')
    with open(ambiguous, 'w', encoding='utf-8') as f:
        f.write('same\nother\nsame')

    res_missing = await tools_svc.execute_tool('str_replace_editor', {
        'command': 'str_replace',
        'path': ambiguous,
        'old_str': 'absent',
        'new_str': 'x',
    })
    assert 'did not appear verbatim' in res_missing

    res_repeated = await tools_svc.execute_tool('str_replace_editor', {
        'command': 'str_replace',
        'path': ambiguous,
        'old_str': 'same',
        'new_str': 'x',
    })
    assert 'Multiple occurrences of old_str' in res_repeated

    res_rel = await tools_svc.execute_tool('str_replace_editor', {
        'command': 'view',
        'path': 'ambiguous.txt',
    })
    assert 'is not an absolute path' in res_rel


def test_rejects_invalid_plugin_config():
    with pytest.raises(ValueError, match='maxOutputChars must be a positive safe integer'):
        StrReplaceEditorPlugin({'maxOutputChars': 0})

    with pytest.raises(ValueError, match='description must be non-empty'):
        StrReplaceEditorPlugin({'description': '   '})
