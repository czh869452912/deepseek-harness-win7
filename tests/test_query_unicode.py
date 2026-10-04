from concurrent.futures import ThreadPoolExecutor
from functools import cmp_to_key
import json
from pathlib import Path
import shutil

import pytest

from dsh.session import icu_collation
from dsh.session.icu_collation import IcuCollator, verify_icu_files
from dsh.session.query_engine import normalized_identity


ASSETS = Path(icu_collation.__file__).parent / 'bin/icu'


@pytest.mark.parametrize('left,right', [('é', 'e\u0301'), ('ab', 'a\u200bb'), ('ab', 'a\u00adb'),
                                       ('ab', 'a\u2060b'), ('a\u0315\u0300', '\u00e0\u0315')])
def test_canonical_and_ignorable_strings_preserve_stable_order(left, right):
    collator = IcuCollator()
    try:
        assert collator.compare(left, right) == 0
        assert collator.compare(right, left) == 0
        assert sorted([right, left], key=cmp_to_key(collator.compare)) == [right, left]
        assert collator.runtime_identity()['normalization'] == 17
    finally:
        collator.close()


def test_nullable_fingerprint_preserves_source_case_order():
    request = dict(query='needle', sessionFilters=[dict(kind='cwd', values=['A', None, 'a'])], eventFilters=[], limit=1)
    assert normalized_identity(request) == '{"scope":"sessions","query":"needle","sessionFilters":[{"kind":"cwd","values":[null,"a","A"]}],"eventFilters":[],"limit":1}'


def test_equivalent_strings_retain_distinct_request_fingerprints():
    request = dict(query='needle', sessionFilters=[dict(kind='cwd', values=['é', 'e\u0301'])], eventFilters=[], limit=1)
    changed = dict(request, sessionFilters=[dict(kind='cwd', values=['e\u0301', 'é'])])
    assert normalized_identity(request) != normalized_identity(changed)


def test_utf16_embedded_nul_and_unpaired_surrogates_are_not_truncated():
    collator = IcuCollator()
    try:
        assert collator.compare('a\0b', 'ab') == 0
        assert collator.compare('a\0b', 'a') > 0
        assert collator.compare('\ud83d\ude00', '😀') == 0
        assert collator.compare('\ud800', '\ud800') == 0
        assert collator.compare('\ud800', '\udc00') != 0
    finally:
        collator.close()


def test_collator_close_is_idempotent_and_refuses_late_comparisons():
    collator = IcuCollator()
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(lambda index: collator.compare('a\u0315\u0300', '\u00e0\u0315'), range(64))) == [0] * 64
    collator.close()
    collator.close()
    with pytest.raises(RuntimeError, match='closed'):
        collator.compare('a', 'b')
    with pytest.raises(RuntimeError, match='closed'):
        collator.runtime_identity()


def test_runtime_identity_copies_metadata_and_reports_loaded_files():
    collator = IcuCollator()
    try:
        identity = collator.runtime_identity()
        identity['manifest']['version'][0] = 1
        identity['version'][0] = 2
        fresh = collator.runtime_identity()
        assert fresh['version'] == [78, 2, 0, 0]
        assert fresh['manifest']['version'] == [78, 2, 0, 0]
        assert [Path(row['path']) for row in fresh['libraries']] == [ASSETS / name for name in icu_collation.ICU_LIBRARIES]
    finally:
        collator.close()


@pytest.mark.parametrize('field,value', [('version', [78, 1, 0, 0]), ('version', [78.0, 2, 0, 0]),
                                       ('unicode_version', [16, 0, 0, 0]), ('cldr_version', [47, 0, 0, 0]),
                                       ('dll_sha256', {}), ('license_sha256', {})])
def test_changed_manifest_refused_before_loading(tmp_path, monkeypatch, field, value):
    manifest = json.loads((ASSETS / 'icu.json').read_text(encoding='utf-8'))
    manifest[field] = value
    (tmp_path / 'icu.json').write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(icu_collation.ctypes, 'CDLL', lambda *args, **kwargs: pytest.fail('must refuse before loading'))
    with pytest.raises(RuntimeError):
        IcuCollator(tmp_path)


@pytest.mark.parametrize('name', ['dsh_icudt78.dll', 'dsh_icuuc78.dll', 'dsh_icuin78.dll', 'ICU-LICENSE', 'LLVM-LICENSE.txt'])
def test_missing_runtime_or_license_refused_before_loading(tmp_path, monkeypatch, name):
    for asset in ASSETS.iterdir():
        if asset.name != name:
            shutil.copy2(str(asset), str(tmp_path / asset.name))
    monkeypatch.setattr(icu_collation.ctypes, 'CDLL', lambda *args, **kwargs: pytest.fail('must refuse before loading'))
    with pytest.raises(FileNotFoundError):
        IcuCollator(tmp_path)


def test_corrupt_private_library_refused_before_loading(tmp_path, monkeypatch):
    for asset in ASSETS.iterdir():
        shutil.copy2(str(asset), str(tmp_path / asset.name))
    (tmp_path / 'dsh_icudt78.dll').write_bytes(b'changed')
    monkeypatch.setattr(icu_collation.ctypes, 'CDLL', lambda *args, **kwargs: pytest.fail('must refuse before loading'))
    with pytest.raises(RuntimeError, match='hash differs'):
        IcuCollator(tmp_path)


def test_legacy_windows_loader_flags_are_used_for_all_libraries(monkeypatch):
    observed = []
    original = icu_collation.ctypes.CDLL
    def load(name, *args, **kwargs):
        assert kwargs.get('winmode') == 0
        observed.append(str(name))
        return original(name, *args, **kwargs)
    monkeypatch.setattr(icu_collation.ctypes, 'CDLL', load)
    collator = IcuCollator()
    try:
        assert collator.compare('a', 'b') < 0
        assert all(str(ASSETS / name) in observed for name in icu_collation.ICU_LIBRARIES)
    finally:
        collator.close()


def test_portable_input_verification_does_not_load_libraries(monkeypatch):
    monkeypatch.setattr(icu_collation.ctypes, 'CDLL', lambda *args, **kwargs: pytest.fail('metadata preflight must not load'))
    directory, manifest = verify_icu_files()
    assert directory == ASSETS
    assert manifest['build']['direct_system_dependencies'] == ['ADVAPI32.dll', 'KERNEL32.dll', 'msvcrt.dll']
