import json
import os
from pathlib import Path
import shutil
import tempfile

import pytest

from scripts import process_artifact_retention as retention
from scripts import verify_release as gate


@pytest.fixture
def external_owner(tmp_path, monkeypatch):
    output_root = tmp_path / '.goose/out'
    output = output_root / 'release'
    output.mkdir(parents=True)
    workspace = Path(tempfile.mkdtemp(prefix='g-')).resolve()
    mapping = dict(format='dsh-release-workspace@2', temporary_parent=str(workspace.parent),
        execution_path=str(workspace), retained_path=str(output / 'pytest-workspace'))
    (output / 'pytest-workspace-mapping.json').write_text(json.dumps(mapping), encoding='utf-8')
    monkeypatch.setenv('DSH_RELEASE_PYTEST_OUTPUT', str(output))
    try:
        yield output_root, output, workspace, mapping
    finally:
        if workspace.exists():
            shutil.rmtree(str(workspace))


def test_mapped_external_finished_case_prunes_only_synthetic_receipt(external_owner):
    root, output, workspace, mapping = external_owner
    folder = workspace / 'test_finished0'
    folder.mkdir()
    (folder / 'portable.zip').write_bytes(retention.FAKE_ARCHIVE)
    receipt = folder / 'receipt.json'
    receipt.write_text('{"runtime":{"checks":["actual runtime"]}}', encoding='utf-8')
    raw = folder / 'source.json'
    raw.write_text('{"actual":"observation"}', encoding='utf-8')
    report = retention.prune_finished_test_folder(root, workspace, folder)
    assert report['removed_files'] == 1 and not receipt.exists()
    assert raw.read_text(encoding='utf-8') == '{"actual":"observation"}'
    assert (folder / 'portable.zip').read_bytes() == retention.FAKE_ARCHIVE


@pytest.mark.parametrize('damage', ['wrong-parent', 'wrong-format', 'nested', 'sibling'])
def test_external_mapping_refuses_foreign_execution(external_owner, damage):
    root, output, workspace, mapping = external_owner
    if damage == 'wrong-parent':
        mapping['temporary_parent'] = str(output.parent)
    elif damage == 'wrong-format':
        mapping['format'] = 'unowned'
    elif damage == 'nested':
        mapping['execution_path'] = str(workspace / 'g-abcdefgh')
    else:
        foreign = Path(tempfile.mkdtemp(prefix='g-')).resolve()
        try:
            with pytest.raises(ValueError, match='owner differs'):
                retention.active_workspace_root(root, foreign, str(output))
        finally:
            shutil.rmtree(str(foreign))
        return
    with pytest.raises(ValueError, match='owner differs'):
        retention.execution_workspace(root, output, mapping)


def test_repository_temp_is_rejected_before_pytest_or_allocation(tmp_path, monkeypatch):
    output = tmp_path / '.goose/out/release'
    output.mkdir(parents=True)
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    monkeypatch.setattr(gate.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(gate, 'run', lambda *args, **kwargs: pytest.fail('pytest must not start'))
    with pytest.raises(RuntimeError, match='outside the repository'):
        gate.run_python_regression('python', output, {})
    assert not list(tmp_path.glob('g-*'))
    assert not (output / 'pytest-workspace-mapping.json').exists()
