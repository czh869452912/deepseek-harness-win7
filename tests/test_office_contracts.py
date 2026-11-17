import json
import os
from pathlib import Path
import shutil

import pytest

from dsh.cordis.utils import _UNDEFINED
from dsh.javascript.runtime import JavaScriptRuntimeError
from dsh.office import contracts
from dsh.office.errors import OfficeKitError


def test_original_contract_batch_retains_valid_results_after_rejection(tmp_path):
    source = str(tmp_path / 'input.docx')
    output = str(tmp_path / 'output.txt')
    rows = contracts.observe([('convert', dict(inputPath=source, outputPath=output)),
                              ('images', dict(inputPath=source, outputDir=str(tmp_path / 'images'), dpi=float('nan'))),
                              ('options', dict(fontDirectories=[], fontMetadataCacheDirectory=False))])
    assert rows[0] == dict(ok=True, value=dict(inputPath=source, outputPath=output, extension='docx', format='txt', recalculate=False))
    assert rows[1] == dict(ok=False, name='TypeError', message='dpi must be between 24 and 600.')
    assert rows[2]['ok'] and rows[2]['value']['includeOfficeFonts'] is False


def test_request_error_categories_remain_actionable(tmp_path):
    with pytest.raises(OfficeKitError) as caught:
        contracts.resolve_request('recalculate', dict(inputPath=str(tmp_path / 'input.docx'), outputPath=str(tmp_path / 'output.xlsx')))
    assert caught.value.code == 'unsupported-format'
    with pytest.raises(TypeError, match='absolute filesystem paths'):
        contracts.resolve_request('convert', dict(inputPath='relative', outputPath='relative'))
    with pytest.raises(ValueError, match='positive safe integer') as caught:
        contracts.resolve_request('options', dict(timeoutMs=0))
    assert caught.value.name == 'RangeError'


def test_undefined_optional_sheet_and_calc_rectangle_use_original_semantics(tmp_path):
    result = contracts.resolve_request('convert', dict(inputPath=str(tmp_path / 'input.xlsx'), outputPath=str(tmp_path / 'output.csv'), sheet=_UNDEFINED))
    assert 'sheet' not in result
    result = contracts.resolve_request('images', dict(inputPath=str(tmp_path / 'input.xlsx'), outputDir=str(tmp_path / 'images'), sheet='Exact', range='$b$2:d4'))
    assert result['range'] == 'B2:D4' and result['sheet'] == 'Exact' and 'pages' not in result


@pytest.mark.parametrize('change', ['manifest', 'resource'])
def test_corrupt_contract_bytes_fail_before_worker_spawn(tmp_path, monkeypatch, change):
    source = contracts.RESOURCES
    for path in source.iterdir():
        shutil.copyfile(str(path), str(tmp_path / path.name))
    path = tmp_path / ('manifest.json' if change == 'manifest' else 'contracts.js')
    path.write_bytes(path.read_bytes() + b'\n')
    monkeypatch.setattr(contracts, 'RESOURCES', tmp_path)
    with pytest.raises(JavaScriptRuntimeError, match='differs'):
        contracts.bootstrap()
