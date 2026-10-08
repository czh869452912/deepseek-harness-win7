"""Actual Portable identity closure for canonical DeepSeek request extensions."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.llm import plugin_package_inventory
from scripts.build_portable import bundle_vendor_identities

ROOT = Path(__file__).resolve().parents[1]


def isolated_installation(directory):
    (directory / 'packages').mkdir(parents=True)
    anchor = directory / 'dsh/llm/plugin_package_inventory.py'
    anchor.parent.mkdir(parents=True)
    anchor.write_text('# isolated installed anchor\n', encoding='utf-8')
    return anchor


def resolver(profile):
    tree = SimpleNamespace(ctx=SimpleNamespace(baseUrl=str(profile)))
    entry = SimpleNamespace(parent=SimpleNamespace(tree=tree), options={'name': '@deepseek-ai/cordis-plugin-timer'})
    loader = SimpleNamespace(harness_plugins={'@deepseek-ai/cordis-plugin-timer': object()}, installation_module_roots=[])
    return plugin_package_inventory.PackageIdentityResolver(str(profile), loader), entry


def test_missing_identity_refuses_but_pinned_bundle_resolves(monkeypatch, tmp_path):
    profile = tmp_path / 'outside-profile'
    profile.mkdir()
    before = isolated_installation(tmp_path / 'before')
    monkeypatch.setattr(plugin_package_inventory, '__file__', str(before))
    lookup, entry = resolver(profile)
    with pytest.raises(ValueError, match='cannot resolve active package'):
        lookup.resolve(entry)
    after = isolated_installation(tmp_path / 'after')
    bundle_vendor_identities(ROOT, after.parents[2])
    monkeypatch.setattr(plugin_package_inventory, '__file__', str(after))
    lookup, entry = resolver(profile)
    expected = json.loads((ROOT / 'reference/vendor/timer/package.json').read_text(encoding='utf-8'))
    assert lookup.resolve(entry) == {key: expected[key] for key in ('name', 'version')}
    for source in (ROOT / 'reference/vendor').glob('*/package.json'):
        for path in (source, source.with_name('LICENSE')):
            assert (after.parents[2] / path.relative_to(ROOT / 'reference')).read_bytes() == path.read_bytes()


@pytest.mark.parametrize('damage', ['missing-license', 'empty-version', 'duplicate-name'])
def test_invalid_vendor_closure_refused_before_publication(tmp_path, damage):
    fixtures = tmp_path / 'fixtures'
    source = fixtures / 'reference/vendor'
    for name in ('first', 'second'):
        directory = source / name
        directory.mkdir(parents=True)
        (directory / 'package.json').write_text(json.dumps(dict(name=name, version='1')), encoding='utf-8')
        (directory / 'LICENSE').write_text('controlled-license\n', encoding='utf-8')
    if damage == 'missing-license':
        (source / 'second/LICENSE').unlink()
    else:
        data = dict(name='first' if damage == 'duplicate-name' else 'second', version='' if damage == 'empty-version' else '1')
        (source / 'second/package.json').write_text(json.dumps(data), encoding='utf-8')
    output = tmp_path / 'candidate'
    with pytest.raises(ValueError):
        bundle_vendor_identities(fixtures, output)
    assert not output.exists()
