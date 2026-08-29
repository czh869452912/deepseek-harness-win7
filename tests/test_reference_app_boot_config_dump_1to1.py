import os
import tempfile
import yaml
import pytest

from dsh.cordis.profile import render_config_dump, dump_config
from dsh.cordis.loader import is_js_expr


def test_render_config_dump_layer_provenance_and_comments():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_yml = os.path.join(tmpdir, 'base.yml')
        with open(base_yml, 'w', encoding='utf-8') as f:
            f.write(
                '- id: shared\n'
                '  name: ./noop.mjs\n'
                '  config:\n'
                '    value: base\n'
                '    key: !!js process.env.DSH_DUMP_SPEC\n'
                '- id: untouched\n'
                '  name: ./noop.mjs\n'
            )

        layers = [
            {
                'label': 'surface.yml',
                'patches': [
                    {'id': 'shared', 'config': {'value': 'surface', 'key': {'__jsExpr': 'process.env.DSH_DUMP_SPEC'}}},
                    {'insert': [{'id': 'surface-extra', 'name': './noop.mjs'}]}
                ]
            },
            {
                'label': 'user.yml',
                'patches': [
                    {'id': 'surface-extra', 'config': {'value': 'user'}}
                ]
            }
        ]

        dump = render_config_dump('dsh-test-bin', base_yml, layers)

        assert '# == base.yml, patched by surface.yml' in dump
        assert '# == base.yml' in dump
        assert '- id: untouched' in dump
        assert '# == surface.yml, patched by user.yml' in dump
        assert '- id: surface-extra' in dump


def test_render_config_dump_file_not_found_raises():
    with pytest.raises(FileNotFoundError) as exc_info:
        render_config_dump('dsh-test-bin', 'nonexistent_base.yml', [])
    assert 'failed to read config' in str(exc_info.value)
