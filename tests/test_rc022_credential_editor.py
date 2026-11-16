import importlib.metadata
import json
import subprocess
import sys
import traceback
from pathlib import Path

import pytest
from ruamel.yaml.error import YAMLError

from dsh.credentials import editor_current as editor
from scripts.rc022_credential_editor_probe import observe


@pytest.mark.asyncio
async def test_admitted_durable_edits_annotations_and_foreign_integer_corpus(tmp_path):
    rows = await observe(tmp_path/'files')
    (tmp_path/'credential-editor-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 184
    assert rows[58]['comments'] == ['c-header', 'c-second', 'c-foreign']
    assert rows[76]['comments'] == ['c-record']
    assert rows[122]['comments'] == ['c-second', 'c-tail']
    assert rows[138]['comments'] == ['c-tail']
    assert rows[144]['comments'] == ['c-flow-first', 'c-flow-second', 'c-tail']
    assert rows[164]['comments'] == []
    for index in range(48, 64):
        assert '9007199254740993123456' in (tmp_path/'files'/(str(index)+'.yaml')).read_text(encoding='utf-8')


def test_edit_library_failures_do_not_quote_secret_or_context(monkeypatch):
    class Broken:
        def __init__(self, **kwargs): pass
        def load(self, text): raise YAMLError('NEVER_QUOTE_PRIVATE_VALUE')
    monkeypatch.setattr(editor, 'YAML', Broken)
    try: editor.render_edit('version: 1\n', 'refs', 'KEY', 'value')
    except ValueError as error:
        assert 'NEVER_QUOTE_PRIVATE_VALUE' not in ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        assert str(error) == 'credentials-local: could not edit the admitted document safely'
    else: pytest.fail('library failure was not surfaced')


def test_portable_dependency_copy_imports_editor_under_python_without_site(tmp_path):
    from scripts.build_portable import bundle_dependencies
    root = Path(__file__).resolve().parents[1]
    for package, version in [('ruamel.yaml', '0.18.16'), ('ruamel.yaml.clib', '0.2.8')]:
        assert importlib.metadata.version(package) == version
        for lock in ['requirements-runtime.lock', 'requirements-runtime-x86.lock']:
            assert package+'=='+version in (root/lock).read_text(encoding='utf-8').splitlines()
    payload = tmp_path/'lib'
    bundle_dependencies([importlib.metadata.distribution(name) for name in ['ruamel.yaml', 'ruamel.yaml.clib', 'PyYAML']], str(payload))
    source = "import sys;sys.path[:0]=sys.argv[1:3];from ruamel.yaml import YAML;assert YAML.__module__.startswith('ruamel.yaml');import _ruamel_yaml;assert _ruamel_yaml.__file__.startswith(sys.argv[1]);from dsh.credentials.editor_current import render_edit;text='version: 1\\nrefs: {KEY: old}\\nforeign: 9007199254740993123456 # retained\\n';result=render_edit(text,'refs','KEY','new');assert '9007199254740993123456' in result;assert '# retained' in result;assert 'new' in result"
    subprocess.run([sys.executable, '-S', '-c', source, str(payload), str(root)], check=True, timeout=15)


def test_renderer_output_is_admitted_before_becoming_a_durable_candidate(monkeypatch):
    from ruamel.yaml.comments import CommentedMap
    class Invalid:
        def __init__(self, **kwargs): pass
        def load(self, text): return CommentedMap(version=1)
        def dump(self, root, stream): stream.write('version: 1\nrefs: [PRIVATE_CANDIDATE')
    monkeypatch.setattr(editor, 'YAML', Invalid)
    with pytest.raises(ValueError, match='invalid document') as caught:
        editor.render_edit('version: 1\n', 'refs', 'KEY', 'new')
    assert 'PRIVATE_CANDIDATE' not in str(caught.value)
