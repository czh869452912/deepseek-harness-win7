"""Opt-in real-provider CLI/tool/cold-resume journey; never prints credentials.

Requires an explicit external credential file and a fresh private output folder.
Only a generated read-only probe document is sent to the selected provider.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml
from dsh.llm.deepseek_config_current import PUBLIC_BASE_URL
from dsh.session.jsonl_current import parseGenerationLogFilename
from dsh.session.jsonl_zstd import decompress_frame, scan_frames


def durable_session_log(home):
    files = [path for path in (home / 'sessions').glob('*/*/*.jsonl.zstd')
             if parseGenerationLogFilename(path.name, 'zstd') is not None]
    if len(files) != 1:
        raise RuntimeError('Expected one durable session log, found {}'.format(len(files)))
    return files[0]


def session_events(path):
    physical = path.read_bytes()
    return [json.loads(line) for frame in scan_frames(physical)['frames']
            for line in decompress_frame(physical[frame['start']:frame['end']]).splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials-file', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--model', default='deepseek-flash')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    key = yaml.safe_load(args.credentials_file.read_text(encoding='utf-8')).get('refs', {}).get('DEEPSEEK_API_KEY')
    if not isinstance(key, str) or not key.strip():
        raise ValueError('External DEEPSEEK_API_KEY is unavailable')
    key = key.strip()
    marker = 'DSH_REAL_PROVIDER_' + uuid.uuid4().hex
    target = output / 'probe.txt'
    target.write_text(marker + '\n', encoding='utf-8')
    home = output / 'home'
    profile = home / 'profiles/headless'
    profile.mkdir(parents=True)
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([
        dict(id='llm-deepseek', config=dict(baseURL=PUBLIC_BASE_URL, maxTokens=1024,
             thinking='disabled', retryPolicy=dict(mode='normal', maxRetries=0), streamIdleTimeoutMs=45000)),
        dict(id='agent-default-model', config=dict(provider='deepseek-official', model=args.model)),
    ]), encoding='utf-8')
    env = {name: value for name, value in os.environ.items()
           if not any(part in name.upper() for part in ('API_KEY', 'API_TOKEN', 'ACCESS_TOKEN', 'REFRESH_TOKEN', 'PYTHONPATH', 'PYTHONHOME'))}
    env.update(DSH_HOME=str(home), DEEPSEEK_API_KEY=key, DSH_TELEMETRY_DISABLED='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    report = dict(scope='Actual DeepSeek authentication, first message, read tool and cold Agent resume; generated document only',
                  model=args.model, endpoint=PUBLIC_BASE_URL, phases=[], status='running')

    def run(name, command):
        started = time.monotonic()
        result = subprocess.run(command, cwd=str(args.root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=150)
        for kind, data in (('stdout', result.stdout), ('stderr', result.stderr)):
            (output / (name + '.' + kind + '.log')).write_bytes(data.replace(key.encode('utf-8'), b'[REDACTED]'))
        report['phases'].append(dict(name=name, exitCode=result.returncode, seconds=round(time.monotonic() - started, 3)))
        if result.returncode:
            raise RuntimeError(name + ' failed; see private redacted logs')
        return result.stdout.decode('utf-8').strip()

    try:
        answer = run('first-turn', [str(args.python.absolute()), str(args.root / 'dsh.py'), '--profile', 'headless',
            'Read this generated test document using the read tool: ' + str(target) + '. Reply only with its complete text. Do not write files or call other tools.'])
        assert marker in answer, 'Real model must return the generated document marker'
        log_path = durable_session_log(home)
        before = session_events(log_path)
        assert any(row.get('type') == 'tool/result' for row in before), 'Actual tool result required'
        identity = before[0]['id']
        code = (ROOT / 'tests/headless_resume_process.py').read_text(encoding='utf-8')
        resumed = run('cold-resume', [str(args.python.absolute()), '-c', code, identity])
        resume = json.loads(resumed.splitlines()[-1])
        assert resume['after'] > resume['before']
        after = session_events(log_path)
        assert len(after) > len(before)
        report.update(status='passed', credentialAccepted=True, realToolResult=True, coldResume=resume,
                      eventCounts=dict(before=len(before), after=len(after)),
                      sessionSha256=hashlib.sha256(log_path.read_bytes()).hexdigest())
    except Exception as error:
        report.update(status='failed', failure=str(error).replace(key, '[REDACTED]'))
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], phases=report['phases'], failure=report.get('failure'))))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
