"""Opt-in actual Desktop composer, real provider/read tool and cold context resume."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml
from dsh.llm.deepseek_config_current import PUBLIC_BASE_URL
from scripts.verify_live_provider import durable_session_log, session_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials-file', type=Path, required=True)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--development-python', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    key = yaml.safe_load(args.credentials_file.read_text(encoding='utf-8'))['refs']['DEEPSEEK_API_KEY'].strip()
    marker = 'DSH_DESKTOP_REAL_' + uuid.uuid4().hex
    workspace = output / 'workspace'
    workspace.mkdir()
    (workspace / 'probe.txt').write_text(marker + '\n', encoding='utf-8')
    profile = output / 'fresh/home/profiles/desktop'
    profile.mkdir(parents=True)
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([
        dict(id='llm-deepseek', config=dict(baseURL=PUBLIC_BASE_URL, maxTokens=1024,
             thinking='disabled', retryPolicy=dict(mode='normal', maxRetries=0), streamIdleTimeoutMs=45000)),
        dict(id='agent-default-model', config=dict(provider='deepseek-official', model='deepseek-flash')),
    ]), encoding='utf-8')
    env = {name: value for name, value in os.environ.items()
           if not any(part in name.upper() for part in ('API_KEY', 'API_TOKEN', 'ACCESS_TOKEN', 'REFRESH_TOKEN', 'PYTHONPATH', 'PYTHONHOME'))}
    env.update(DEEPSEEK_API_KEY=key, DSH_TELEMETRY_DISABLED='1', PYTHONDONTWRITEBYTECODE='1')
    report = dict(status='running', scope='Actual original Desktop composer, generated read-only document, real DeepSeek and cold context resume', phases=[])
    try:
        for phase in ('fresh', 'cold'):
            target = output / phase
            # The observer owns its output mkdir; only the explicit profile was prepared.
            if phase == 'fresh':
                staged = output / 'staged-home'
                (target / 'home').rename(staged)
                target.rmdir()
            command = [str(args.node.absolute()), str(ROOT / 'scripts/oracles/desktop_upgrade_current.mjs'),
                       '--executable', str(args.executable.absolute()), '--output', str(target),
                       '--current-onboarding', 'true', '--live-provider', marker, '--workspace', str(workspace)]
            if phase == 'fresh':
                # Restore before spawn, after the observer has claimed its fresh directory.
                command += ['--prepared-home', str(staged)]
            else:
                command += ['--home', str(output / 'fresh/home')]
            if args.development_python:
                command += ['--development-root', str(ROOT), '--development-python', str(args.development_python.absolute())]
            result = subprocess.run(command, env=env, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
            (output / (phase + '.log')).write_bytes(result.stdout.replace(key.encode('utf-8'), b'[REDACTED]'))
            assert result.returncode == 0, phase + ' actual Desktop journey failed'
            observed = json.loads((target / 'report.json').read_text(encoding='utf-8'))
            report['phases'].append(dict(phase=phase, checks=observed['checks'], answer=observed['liveProvider']))
        events = session_events(durable_session_log(output / 'fresh/home'))
        assert any(row.get('type') == 'tool/result' and marker in json.dumps(row) for row in events), 'Missing durable read result'
        assert sum(row.get('type') == 'user/message' for row in events) >= 2, 'Missing durable cold turn'
        report.update(status='passed', realReadToolResult=True, durableEvents=len(events))
    except Exception as error:
        report.update(status='failed', failure=str(error).replace(key, '[REDACTED]'))
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], failure=report.get('failure'))))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
