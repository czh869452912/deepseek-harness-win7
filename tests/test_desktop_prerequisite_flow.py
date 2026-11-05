"""Execute the installer policy in Windows PowerShell with servicing boundaries mocked."""
import base64
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def observe_flows(architecture):
    if os.name != 'nt':
        pytest.skip('Windows PowerShell policy consumer')
    script = r'''
$ErrorActionPreference='Stop'
. '__SCRIPT__' -LibraryOnly
$results=@()
foreach($scenario in @('ready','standard','modern','wmf3','pending','install','already','reboot','failure','unavailable','reboot-after')) {
  $script:scenario=$scenario
  $script:steps=New-Object Collections.Generic.List[string]
  $script:state=@{Win7=$true;Net=$false;PowerShell=$false;SSU=$false;SHA2=$false;D3D=$false;WMF3=$false}
  if($scenario -eq 'ready'){foreach($key in @('Net','PowerShell','SSU','SHA2','D3D')){$script:state[$key]=$true}}
  if($scenario -eq 'modern'){$script:state.Win7=$false}
  if($scenario -eq 'wmf3'){$script:state.WMF3=$true}
  function Write-SetupLog([string]$Text) { }
  function Get-PrerequisiteState { return $script:state }
  function Test-RebootPending { return $script:scenario -eq 'pending' -or ($script:scenario -eq 'reboot-after' -and $script:steps.Count -gt 0) }
  function Invoke-OfflineInstaller([string]$Name,[string]$Arguments) {
    $script:steps.Add($Name)
    if($script:scenario -eq 'failure'){return 2149842967}
    if($script:scenario -eq 'reboot'){return 3010}
    $key=@{'ssu-x64.msu'='SSU';'sha2-x64.msu'='SHA2';'d3d-x64.msu'='D3D';'net472.exe'='Net';'wmf-x64.msu'='PowerShell'}[$Name]
    if(!$key){throw ('Unexpected installer input: '+$Name)}
    if($script:scenario -ne 'unavailable'){$script:state[$key]=$true}
    if($script:scenario -eq 'already'){return 2359302}
    return 0
  }
  try {
    $edition='aio';if($scenario -eq 'standard'){$edition='standard'}
    $code=Invoke-Prerequisites $edition 'x64'
    $results+=@{scenario=$scenario;code=$code;steps=@($script:steps.ToArray())}
  } catch {$results+=@{scenario=$scenario;error=$_.Exception.Message;steps=@($script:steps.ToArray())}}
}
$results | ConvertTo-Json -Depth 8 -Compress
'''.replace('__SCRIPT__', str(ROOT / 'apps/desktop/installer/prerequisites.ps1').replace("'", "''")).replace('x64', architecture)
    command = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-EncodedCommand', command], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stderr
    return {row['scenario']: row for row in json.loads(result.stdout)}


@pytest.fixture(scope='module')
def flows():
    return observe_flows('x64')


def test_x86_policy_selects_matching_system_packages_and_preserves_stop_boundaries():
    rows = observe_flows('x86')
    for scenario in ('install', 'already'):
        assert rows[scenario]['code'] == 0
        assert rows[scenario]['steps'] == ['ssu-x86.msu', 'sha2-x86.msu', 'd3d-x86.msu', 'net472.exe', 'wmf-x86.msu']
    for scenario in ('reboot', 'reboot-after'):
        assert rows[scenario]['code'] == 3010 and rows[scenario]['steps'] == ['ssu-x86.msu']
    assert rows['failure']['steps'] == ['ssu-x86.msu'] and '2149842967' in rows['failure']['error']
    assert rows['standard']['code'] == 2 and rows['standard']['steps'] == []
    assert rows['wmf3']['code'] == 3 and rows['wmf3']['steps'] == []


@pytest.mark.parametrize('scenario,code', [('ready', 0), ('standard', 2), ('modern', 2), ('wmf3', 3), ('pending', 3010)])
def test_no_unrequested_or_inapplicable_system_mutations(flows, scenario, code):
    assert flows[scenario] == dict(scenario=scenario, code=code, steps=[])


@pytest.mark.parametrize('scenario', ['install', 'already'])
def test_verified_install_order_and_already_installed_status(flows, scenario):
    assert flows[scenario]['code'] == 0
    assert flows[scenario]['steps'] == ['ssu-x64.msu', 'sha2-x64.msu', 'd3d-x64.msu', 'net472.exe', 'wmf-x64.msu']


@pytest.mark.parametrize('scenario', ['reboot', 'reboot-after'])
def test_servicing_reboot_stops_before_next_patch(flows, scenario):
    assert flows[scenario]['code'] == 3010
    assert flows[scenario]['steps'] == ['ssu-x64.msu']


def test_failed_patch_blocks_remaining_installers(flows):
    assert 'exit=2149842967' in flows['failure']['error']
    assert flows['failure']['steps'] == ['ssu-x64.msu']


def test_exit_zero_does_not_replace_actual_postinstall_detection(flows):
    assert 'remains unavailable: SSU' in flows['unavailable']['error']


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows child exit codes')
def test_offline_installer_collects_real_failure_restart_and_unsigned_status(tmp_path):
    # cmd only exits; this executes no servicing package and needs no elevation.
    import shutil
    shutil.copyfile(os.environ['COMSPEC'], str(tmp_path / 'exit-fixture.exe'))
    log = tmp_path / 'installer.log'
    script = r'''
$ErrorActionPreference='Stop'
. '__SCRIPT__' -LibraryOnly
$Payload='__PAYLOAD__'
$LogPath='__LOG__'
$rows=@()
foreach($expected in @(0,7,3010,1641,2359302,2149842967)) {
  $actual=Invoke-OfflineInstaller 'exit-fixture.exe' ('/c exit '+$expected)
  $rows+=@{expected=$expected;actual=$actual}
}
Write-Output ('RESULT_JSON='+($rows | ConvertTo-Json -Compress))
'''
    for name, value in dict(SCRIPT=ROOT / 'apps/desktop/installer/prerequisites.ps1',
                            PAYLOAD=tmp_path, LOG=log).items():
        script = script.replace('__' + name + '__', str(value).replace("'", "''"))
    command = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-InputFormat', 'None',
                             '-ExecutionPolicy', 'Bypass', '-EncodedCommand', command],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout
    rows = json.loads(next(line[len('RESULT_JSON='):] for line in result.stdout.splitlines()
                           if line.startswith('RESULT_JSON=')))
    assert [row['actual'] for row in rows] == [0, 7, 3010, 1641, 2359302, 2149842967]
    diagnostic = log.read_text(encoding='utf-8-sig')
    for row in rows:
        assert 'exit=' + str(row['expected']) in diagnostic
