"""Actual installed Schedule/Discover fresh and cold original-browser checks."""
import argparse
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rc022_gate_runner import digest, execute, remove_owned
from scripts.verify_portable import product_environment


def validate_observations(observed, browser, portable, candidate=ROOT):
    if (observed.get('passed') is not True or browser.get('passed') is not True
            or browser.get('remoteMux') is not True or browser.get('errors') or browser.get('responses')):
        raise ValueError('Installed application/browser observation failed')
    runtime = observed.get('runtime', {})
    if (runtime.get('root') != str(portable.resolve())
            or runtime.get('executable') != str((portable / 'python.exe').resolve())
            or not runtime.get('python', '').startswith('3.8.10 ')):
        raise ValueError('Installed application runtime differs')
    modules = observed.get('modules', {})
    required = {'dsh/boot/profile_boot.py', 'dsh/typert/gateway_authorized.py',
                'dsh/schedule/service_current.py', 'dsh/host/browser_compat/plugin.py'}
    if observed.get('kind') == 'market': required.add('dsh/boot/plugin_market_022.py')
    if observed.get('kind') == 'question':
        required.update({'dsh/interaction/user_questions_current.py', 'dsh/interaction/question_projection.py',
                         'dsh/interaction/question_wait.py', 'dsh/interaction/tool_ask_user_current.py'})
    if not required <= modules.keys(): raise ValueError('Installed application import closure incomplete')
    for name, value in modules.items():
        if ('\\' in name or ':' in name or Path(name).is_absolute() or '..' in Path(name).parts
                or not name.startswith(('dsh/', 'apps/'))
                or digest(candidate / name) != value or digest(portable / name) != value):
            raise ValueError('Installed application imported bytes outside the selected candidate: ' + name)


def phase(options):
    output = options.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    config = dict(kind=options.kind, output=str(output), home=str(options.home.resolve()),
                  browser=str(options.browser.resolve()), fixture=options.fixture)
    if options.previous: config['previous'] = str(options.previous.resolve())
    configuration = output / 'host-input.json'
    configuration.write_text(json.dumps(config), encoding='utf-8')
    command = [str(options.portable / 'python.exe'), '-I', '-B', '-u',
               str(ROOT / 'scripts/current_application_host.py'), str(configuration)]
    environment = product_environment(options.portable, options.home.parent)
    environment['DSH_HOME'] = str(options.home.resolve())
    child = subprocess.Popen(command, cwd=str(options.home.parent), env=environment,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines = queue.Queue()
    def collect():
        with (output / 'host.log').open('wb') as log:
            for line in iter(child.stdout.readline, b''):
                log.write(re.sub(rb'token=[^\s]+', b'token=[redacted]', line)); log.flush()
                lines.put(line)
        lines.put(None)
    reader = threading.Thread(target=collect, daemon=True); reader.start()
    report = dict(command=command, passed=False)
    try:
        deadline = time.monotonic() + 120
        while True:
            line = lines.get(timeout=max(.01, deadline - time.monotonic()))
            if line is None: raise RuntimeError('Installed application host exited before readiness')
            if line.strip() == b'CURRENT_APPLICATION_READY': break
        observer = ROOT / ('scripts/oracles/rc022_' + options.kind + '_browser.mjs')
        browser_command = [str(options.node), str(observer), str(options.source), str(output)]
        with (output / 'browser.log').open('wb') as log:
            completed = subprocess.run(browser_command, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, timeout=180)
        report['browser_command'] = browser_command
        if completed.returncode: raise RuntimeError('Original application browser failed')
        child.stdin.write(b'finish\n'); child.stdin.flush()
        code = child.wait(timeout=60)
        if code: raise RuntimeError('Installed application state verification failed')
        observed = json.loads((output / 'host-observations.json').read_text(encoding='utf-8'))
        validate_observations(observed, json.loads((output / 'browser-observations.json').read_text(encoding='utf-8')),
                              options.portable)
        report['passed'] = True
    finally:
        if child.poll() is None: child.kill(); child.wait(timeout=15)
        reader.join(10)
        report['host_exit_code'] = child.returncode
        # Retain semantic/browser observations and logs, remove live credentials.
        (output / 'browser-config.json').unlink(missing_ok=True)
        (output / 'phase.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


def journeys(portable, workspace, output, source, node, browser, kinds=None):
    portable, workspace, source, node, browser = [path.resolve() for path in
                                                 (portable, workspace, source, node, browser)]
    workspace.mkdir(parents=True, exist_ok=True)
    from scripts.rc022_market_browser_probe import Handler
    fixture = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True); thread.start()
    url = 'http://127.0.0.1:' + str(fixture.server_port)
    rows = []
    try:
        for kind in kinds or ['schedule', 'market', 'question']:
            home = workspace / ('application-' + kind)
            previous = None
            for mode in ['fresh', 'cold']:
                destination = output / (kind + '-' + mode)
                command = [sys.executable, str(Path(__file__).resolve()), '--phase', '--kind', kind,
                    '--portable', str(portable), '--home', str(home), '--output', str(destination),
                    '--source', str(source), '--node', str(node), '--browser', str(browser), '--fixture', url]
                if previous: command += ['--previous', str(previous)]
                execute(command, ROOT, output, kind + '-' + mode, dict(os.environ), 360)
                observed = json.loads((destination / 'host-observations.json').read_text(encoding='utf-8'))
                rows.append(dict(kind=kind, phase=mode, report=str(destination / 'host-observations.json'),
                                 sha256=digest(destination / 'host-observations.json')))
                previous = destination / 'host-observations.json'
            # Both processes have exited and all durable observations are saved.
            # Keep raw session bytes before retiring synthetic profiles/caches.
            sessions = home / 'sessions'
            if sessions.is_dir():
                import shutil
                shutil.copytree(str(sessions), str(output / (kind + '-sessions')))
            removed = remove_owned(home)
            (output / (kind + '-cleanup.json')).write_text(json.dumps(dict(bytes_removed=removed), indent=2), encoding='utf-8')
    finally:
        fixture.shutdown(); fixture.server_close(); thread.join(5)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', action='store_true')
    for name in ['portable', 'output', 'source', 'node', 'browser', 'home']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--kind', choices=['schedule', 'market', 'question'])
    parser.add_argument('--fixture'); parser.add_argument('--previous', type=Path)
    options = parser.parse_args()
    if options.phase: phase(options)
    else:
        options.output.mkdir(parents=True, exist_ok=False)
        rows = journeys(options.portable, options.home, options.output, options.source, options.node, options.browser,
                        [options.kind] if options.kind else None)
        (options.output / 'report.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
