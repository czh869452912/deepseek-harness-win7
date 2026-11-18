"""Current frontend identity and retained Win7 shell origin stay distinct."""
import copy
import json

import pytest

from scripts import build_desktop as builder


def test_desktop_current_frontend_keeps_explicit_historical_shell_origin():
    value = builder.desktop_source_inputs()
    assert value['targetUpstream'] == '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
    assert value['compatibility']['sourceCommit'] != value['targetUpstream']
    assert value['upstreamDesktopProtocol']['version'] == 4
    assert value['compatibility']['carrierVersion'] == 3


@pytest.mark.parametrize('damage', ['target', 'protocol', 'source-bytes', 'frontend',
                                   'origin-bytes', 'origin-label', 'carrier', 'retained-bytes'])
def test_desktop_rejects_stale_current_inputs_and_relabelled_shell(tmp_path, monkeypatch, damage):
    value = copy.deepcopy(builder.desktop_source_inputs())
    origin = json.loads((builder.ROOT / value['compatibility']['manifest']).read_text(encoding='utf-8'))
    files = {}
    for row in origin['inputs']:
        files[row['target']] = (builder.ROOT / row['target']).read_bytes()
    protocol = value['upstreamDesktopProtocol']
    files['reference/' + protocol['source']] = (builder.ROOT / 'reference' / protocol['source']).read_bytes()
    files[value['frontend']['manifest']] = (builder.ROOT / value['frontend']['manifest']).read_bytes()
    files['migration/baseline.json'] = json.dumps(dict(target_upstream=value['targetUpstream'])).encode('utf-8')
    if damage == 'target': value['targetUpstream'] = 'old'
    if damage == 'protocol': protocol['version'] = 3
    if damage == 'source-bytes': files['reference/' + protocol['source']] = b'foreign'
    if damage == 'frontend': value['frontend']['sha256'] = '0' * 64
    if damage == 'carrier': value['compatibility']['carrierVersion'] = 4
    if damage == 'retained-bytes': files[origin['inputs'][0]['target']] = b'foreign'
    if damage == 'origin-label':
        origin['sourceCommit'] = value['compatibility']['sourceCommit'] = value['targetUpstream']
    for name, data in files.items():
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    origin_path = tmp_path / value['compatibility']['manifest']
    origin_path.write_text(json.dumps(origin), encoding='utf-8')
    value['compatibility']['sha256'] = builder.digest(origin_path)
    if damage == 'origin-bytes': origin_path.write_text('{}', encoding='utf-8')
    (tmp_path / 'apps/desktop/source-input.json').write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    with pytest.raises(ValueError): builder.desktop_source_inputs()
