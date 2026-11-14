import asyncio
import os
from pathlib import Path
import time
import pytest
from dsh.cordis import hmr_files
from dsh.cordis.hmr_files import ModuleFiles
from scripts import rc022_hmr_files_probe as probe


def test_actual_file_observation_journey(tmp_path):
    probe.prepare(tmp_path)
    rows = asyncio.run(probe.native())
    by_step = {row['step']:row for row in rows}
    assert by_step[4]['stale'] == ['b','c','missing','node:fs']
    assert by_step[6]['stale'] == ['c','missing']
    assert by_step[13]['stale'] == ['b','missing']
    assert by_step[19]['stale'] == ['edge']
    assert by_step[23]['stale'] == ['edge']
    assert by_step[25]['stale'] == by_step[27]['stale'] == []
    assert by_step[29]['stale'] == ['a']
    assert by_step[37]['stale'] == ['after-tick']


def test_clock_marker_is_owned_and_removed_even_on_stat_failure(tmp_path,monkeypatch):
    original_create = hmr_files.tempfile.mkdtemp; created = []
    def create(**kwargs):
        path = original_create(dir=str(tmp_path),**kwargs); created.append(Path(path)); return path
    monkeypatch.setattr(hmr_files.tempfile,'mkdtemp',create)
    assert abs(ModuleFiles().now()-time.time()*1000) < 2000
    assert all(not path.exists() for path in created)
    original_stat = hmr_files.os.stat
    def stat(path,*args,**kwargs):
        if str(path).endswith(os.sep+'now'): raise OSError('marker stat failed')
        return original_stat(path,*args,**kwargs)
    monkeypatch.setattr(hmr_files.os,'stat',stat)
    with pytest.raises(OSError,match='marker stat failed'): ModuleFiles().now()
    assert all(not path.exists() for path in created)


def test_clock_fallback_when_temp_root_is_unwritable(monkeypatch):
    def denied(**kwargs): raise OSError('read-only temporary root')
    monkeypatch.setattr(hmr_files.tempfile,'mkdtemp',denied)
    before = int(time.time()*1000)
    assert ModuleFiles().now() >= before


def test_same_identity_keeps_loaded_code_and_non_file_urls_are_stale(tmp_path):
    file = tmp_path/'module.py'; file.write_text('a',encoding='utf-8')
    url = file.as_uri(); tracker = ModuleFiles(); info = file.stat()
    tracker.observe([url],{'at':info.st_mtime*1000+1000})
    file.write_text('b',encoding='utf-8')
    os.utime(str(file),ns=(info.st_atime_ns,info.st_mtime_ns))
    assert tracker.compare([url])['stale'] == set()
    assert tracker.compare(['node:fs',url+'?query#hash'])['stale'] == {'node:fs',url+'?query#hash'}
