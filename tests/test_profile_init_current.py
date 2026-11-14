"""Staged replacement, independent template metadata and real launcher consumers."""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from dsh.boot.profile import PROFILE_TEMPLATES, init_profile, load_profile_directory
from dsh.boot.profile_boot import initialize_profile_from_default, prepare_profile, run_profile, INSTALL_ANCHOR
from dsh.boot.dump_config import run_dump_config
from scripts.oracles.profile_init_current_python import execute
from scripts.session_format_oracle import json_equal

CASES=json.loads((Path(__file__).resolve().parents[1]/'scripts/oracles/profile_init_current_cases.json').read_text(encoding='utf-8'))


# The immutable rc.3 initialization IO observations remain historical. Only
# their unchanged argument cases apply to the current parser; rc022 replacement
# IO is observed independently in test_rc022_profile_replace.
@pytest.mark.parametrize('case',[row for row in CASES if row['operation']=='args'],ids=lambda case:case['case'])
def test_existing_profile_launcher_argument_contract(case):assert json_equal(execute(case),case['expected'])


def test_product_templates_remain_explicit_and_independent(tmp_path):
    for key,template in PROFILE_TEMPLATES.items():
        initialize_profile_from_default('custom-'+key,key,str(tmp_path))
        directory=tmp_path/'profiles'/('custom-'+key)
        manifest=json.loads((directory/'package.json').read_text(encoding='utf-8'))
        assert manifest['dependencies']=={} and manifest['dsh']['profile']==dict(bundles=template['bundles'])
        assert 'fromDefaultProfile' not in manifest['dsh']['profile']
        with pytest.raises(RuntimeError,match='names shipped profile'):
            initialize_profile_from_default(key,'web',str(tmp_path))


def test_failure_removes_only_exclusively_claimed_directory_and_can_retry(tmp_path):
    other=tmp_path/'profiles'/'other';other.mkdir(parents=True);(other/'keep').write_text('keep',encoding='utf-8')
    def broken(directory,*args):
        Path(directory).mkdir(parents=True);Path(directory,'partial').write_text('partial',encoding='utf-8');raise RuntimeError('failed writing template')
    with patch('dsh.boot.profile_boot.init_profile',broken):
        with pytest.raises(RuntimeError,match='failed writing template'):
            initialize_profile_from_default('rescue','web',str(tmp_path))
    assert not (tmp_path/'profiles'/'rescue').exists() and (other/'keep').read_text(encoding='utf-8')=='keep'
    initialize_profile_from_default('rescue','web',str(tmp_path))
    assert (tmp_path/'profiles'/'rescue'/'package.json').is_file()


def test_cleanup_failure_preserves_staging_for_diagnosis(tmp_path):
    first,second=RuntimeError('write failed'),OSError('cleanup denied')
    with patch('dsh.boot.profile_boot.init_profile',side_effect=first),patch('dsh.boot.profile_boot.shutil.rmtree',side_effect=second):
        with pytest.raises(OSError,match='cleanup denied'):
            initialize_profile_from_default('rescue','web',str(tmp_path))
    assert not (tmp_path/'profiles'/'rescue').exists()
    assert len(list((tmp_path/'profiles').glob('.rescue.staging-*')))==1


def test_two_synchronized_actual_processes_leave_a_complete_profile(tmp_path):
    child=tmp_path/'claim.py'
    child.write_text('''import sys,time
from pathlib import Path
from dsh.boot.profile_boot import initialize_profile_from_default
home=Path(sys.argv[1]);(home/sys.argv[2]).write_text('ready',encoding='utf-8')
deadline=time.monotonic()+10
while not (home/'start').exists():
 if time.monotonic()>deadline:raise RuntimeError('barrier timeout')
 time.sleep(.01)
try:initialize_profile_from_default('rescue',sys.argv[3],str(home))
except RuntimeError as error:
 print(str(error));raise SystemExit(1)
''',encoding='utf-8')
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]));children=[]
    try:
        for index,template in enumerate(('web','headless')):
            children.append(subprocess.Popen([sys.executable,str(child),str(tmp_path),'ready'+str(index),template],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        deadline=time.monotonic()+8
        while not all((tmp_path/('ready'+str(i))).exists() for i in range(2)):
            assert time.monotonic()<deadline;time.sleep(.01)
        (tmp_path/'start').write_text('start',encoding='utf-8')
        results=[process.communicate(timeout=8) for process in children]
        assert 0 in [process.returncode for process in children],results
        for process,output in zip(children,results):
            if process.returncode:assert b'was recreated concurrently' in output[0],output
        manifest=json.loads((tmp_path/'profiles'/'rescue'/'package.json').read_text(encoding='utf-8'))
        assert manifest['dsh']['profile'] in [dict(bundles=PROFILE_TEMPLATES[key]['bundles']) for key in ('web','headless')]
    finally:
        for process in children:
            if process.poll() is None:process.kill()
            process.communicate(timeout=5)


def test_dump_explicit_template_replacement_resets_user_patch(tmp_path):
    text=run_dump_config('rescue',True,dsh_home=str(tmp_path),from_default_profile='web')
    assert '@deepseek-ai/dsh-web-app' in text or 'web-app' in text
    directory=tmp_path/'profiles'/'rescue';user=directory/'cordis.patch.yml'
    user.write_text('- id: hand-edited\n  disabled: true\n',encoding='utf-8');before=user.read_bytes()
    run_dump_config('rescue',True,dsh_home=str(tmp_path),from_default_profile='web')
    assert user.read_bytes()!=before and 'hand-edited' not in user.read_text(encoding='utf-8')


def test_application_owned_profile_loads_without_home_or_shipped_normalization(tmp_path):
    directory=tmp_path/'application'/'desktop';init_profile(str(directory),[], 'startup')
    (directory/'cordis.patch.yml').write_text('broken: [yaml',encoding='utf-8')
    loaded=load_profile_directory('test',str(directory),INSTALL_ANCHOR,dict(userLayer=False))
    assert loaded.name=='desktop' and loaded.patchReload=='startup' and loaded.patches==[] and loaded.layers==[]
    with pytest.raises(Exception):load_profile_directory('test',str(directory),INSTALL_ANCHOR)


@pytest.mark.asyncio
async def test_profile_run_initializes_before_python_lease_claim_then_boots_actual_tree(tmp_path):
    # The public run_profile claims an installer/host lease before its internal
    # compose. Initialization must happen first, or the lease's mkdir falsely
    # makes a fresh target look like pre-existing state.
    from dsh.cordis.environment import LaunchEnvironmentSnapshot
    with patch.dict(PROFILE_TEMPLATES,{'fixture':dict(bundles=[],patchReload='startup')}):
        result=await asyncio.wait_for(run_profile(dict(profile='rescue',fromDefaultProfile='fixture',dshHome=str(tmp_path),environment=LaunchEnvironmentSnapshot([]),args=[],waitForExit=False)),10)
    try:
        assert result['ctx'].get('loader') is not None
        assert (tmp_path/'profiles'/'rescue'/'package.json').is_file()
    finally:
        await result['ctx'].fiber.dispose()
