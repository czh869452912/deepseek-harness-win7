"""Coordinate one UAC elevation and normal-user GUI checks of installed NSIS apps."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True,
                        help='JSON with lanes [{id,installer,previous?}], using absolute paths')
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--current-onboarding', action='store_true',
                        help='Observe the current account/API-key onboarding and version-5 future-history fixture')
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    assert plan['lanes'] and len({lane['id'] for lane in plan['lanes']}) == len(plan['lanes'])
    for lane in plan['lanes']:
        assert lane['id'].replace('-', '').isalnum()
        for name in ('installer', 'previous'):
            if lane.get(name):
                path = Path(lane[name])
                assert path.is_absolute() and path.is_file(), name
    plan.update(output=str(output), publication=str(ROOT / 'apps/desktop/installer/publish-installation.ps1'),
                cleanupScript=str(ROOT / 'apps/desktop/installer/uninstall-files.ps1'))
    frozen = output / 'administrator-plan.json'
    frozen.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    # Escape PowerShell literals; executable arguments are separately quoted for
    # the Windows command line. No untrusted text becomes PowerShell source.
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = ROOT / 'scripts/verify_desktop_installation.ps1'
    parameters = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + str(script) + '" -Plan "' + str(frozen) + '"'
    command = "$ErrorActionPreference='Stop';try{$p=Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden -PassThru -ArgumentList " + literal(parameters) + ';$p.WaitForExit();exit $p.ExitCode}catch{[Console]::Error.WriteLine($_.Exception.Message);exit 1}'
    elevated = subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                stdout=(output / 'uac.stdout.log').open('wb'), stderr=(output / 'uac.stderr.log').open('wb'))
    report = dict(status='running', lanes=[])
    active = None
    try:
        for lane in plan['lanes']:
            directory = output / lane['id']
            ready = directory / 'installed.json'
            deadline = time.monotonic() + 900
            while not ready.is_file():
                if elevated.poll() is not None:
                    raise RuntimeError('Administrator runner exited before ' + lane['id'])
                if time.monotonic() > deadline:
                    raise RuntimeError('Administrator readiness deadline: ' + lane['id'])
                time.sleep(.2)
            installed = json.loads(ready.read_text(encoding='utf-8-sig'))
            active = directory
            checks = []
            for phase in ('fresh', 'cold'):
                command = [str(args.node.absolute()), str(ROOT / 'scripts/oracles/desktop_upgrade_current.mjs'),
                           '--executable', installed['executable'], '--output', str(directory / phase)]
                command += ['--seed', 'plaintext'] if phase == 'fresh' else ['--home', str(directory / 'fresh/home')]
                if args.current_onboarding:
                    command += ['--current-onboarding', 'true']
                started = time.monotonic()
                with (directory / (phase + '.log')).open('wb') as log:
                    observed = subprocess.run(command, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, timeout=240)
                assert observed.returncode == 0, lane['id'] + ' ' + phase + ' GUI failed'
                checks.append(dict(phase=phase, exitCode=observed.returncode, seconds=round(time.monotonic() - started, 3)))
            (directory / 'gui-complete.json').write_text(json.dumps(dict(passed=True)), encoding='utf-8')
            active = None
            report['lanes'].append(dict(id=lane['id'], gui=checks))
        assert elevated.wait(timeout=600) == 0, 'Administrator lifecycle failed'
        administration = json.loads((output / 'administrator-report.json').read_text(encoding='utf-8-sig'))
        assert administration['status'] == 'passed' and administration['restored']
        report.update(status='passed', administrator=administration)
    except Exception as error:
        report.update(status='failed', failure=str(error))
        if active is not None:
            (active / 'gui-complete.json').write_text(json.dumps(dict(passed=False)), encoding='utf-8')
        # The privileged runner owns restoration. Never terminate it in the
        # middle of restoring registry/shortcut backups.
        try:
            report['administratorExitCode'] = elevated.wait(timeout=60)
        except subprocess.TimeoutExpired:
            report['administratorStillRestoring'] = True
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], lanes=len(report['lanes']), failure=report.get('failure'))))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
