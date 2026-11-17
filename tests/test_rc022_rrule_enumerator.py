import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from dsh.javascript.rrule_enumerator import enumerate_wall,bootstrap
from scripts.rc022_rrule_enumerator_probe import observe


@pytest.mark.asyncio
async def test_pinned_enumerator_observations_and_bounded_pages(tmp_path):
    rows=await observe()
    (tmp_path/'rrule-enumerator-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==60
    assert rows[0]==[1704067200000+420000*index for index in range(10)]
    assert rows[-6:]==[[],None,[],None,[],None]
    assert 'rrulestr' in bootstrap()


def test_private_query_validation():
    with pytest.raises(ValueError):enumerate_wall('bad',0,0,limit=10081)
    with pytest.raises(ValueError):enumerate_wall('bad',0,0,mode='eval')


def test_x86_worker_runs_same_pinned_enumerator(tmp_path):
    binary=os.environ.get('DSH_TEST_X86_PYTHON')
    if not binary:pytest.skip('x86 Python not configured')
    root=Path(__file__).resolve().parents[1]
    code="import sys;sys.path.insert(0,sys.argv[1]);from dsh.javascript.rrule_enumerator import enumerate_wall;import json;print(json.dumps(enumerate_wall('RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1',1704067200000,1704067200000,limit=3)))"
    result=subprocess.run([binary,'-c',code,str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    (tmp_path/'x86-rrule-observations.json').write_text(json.dumps(dict(exit_code=result.returncode,stdout=result.stdout.decode('utf-8'),stderr=result.stderr.decode('utf-8'))),encoding='utf-8')
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)==[1706659200000,1709164800000,1711670400000]
