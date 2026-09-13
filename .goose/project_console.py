"""Loopback-only Goose dashboard. No framework, proxy or external service."""
import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil
import sys
import time
from urllib.parse import parse_qs, urlsplit

from console_runtime import load_config, config_revision, write_config, read_events
from project_store import Store

ROOT = Path(__file__).resolve().parents[1]


class Console:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.store = Store(self.root / '.goose/runs/project/state.sqlite3')
        self.token = secrets.token_urlsafe(32)

    def run_dir(self, task):
        row = next((r for r in self.store.rows() if r['id'] == task), None)
        if not row or not row['run_dir']:
            raise ValueError('Task has no retained run')
        repair = (row.get('feedback') or {}).get('plan_repair_run') if row['state'] == 'PLAN_REPAIR' else None
        path = Path(repair or row['run_dir']).resolve()
        # The HTTP API accepts task IDs, never arbitrary filesystem paths.
        try:
            path.relative_to(self.root / '.goose/runs')
        except ValueError:
            raise ValueError('Run belongs to another host; import the checkpoint first')
        return path

    def status(self):
        view = self.store.view()
        tasks = []
        for task in view['tasks']:
            live = {}
            if task.get('run_dir'):
                try:
                    live = json.loads((self.run_dir(task['id']) / 'status.json').read_text(encoding='utf-8'))
                    if (live.get('last_activity') or {}).get('kind') == 'heartbeat':
                        recent, _ = read_events(self.run_dir(task['id']) / 'progress.jsonl', -1, 2000)
                        useful = [e for e in recent if e.get('kind') != 'heartbeat']
                        if useful:
                            live['last_activity'] = useful[-1]
                    if not live.get('model') and live.get('phase'):
                        recipe = self.run_dir(task['id']) / ('%02d-%s.yaml' % (task['round'], live['phase']))
                        if recipe.exists():
                            settings = json.loads(recipe.read_text(encoding='utf-8')).get('settings', {})
                            live['model'] = settings.get('goose_model')
                            live['provider'] = settings.get('goose_provider')
                except (OSError, ValueError):
                    pass
            tasks.append({k: task.get(k) for k in ('id', 'state', 'round', 'head', 'error',
                                                   'waiting_on', 'waiting_for_writer')})
            tasks[-1]['live'] = {k: live.get(k) for k in ('phase', 'execution_state', 'model', 'provider',
                    'config_revision', 'attempt', 'test_python', 'last_activity', 'last_heartbeat')}
            tasks[-1]['has_run'] = bool(task.get('run_dir'))
            if (str(tasks[-1]['error']).startswith('Waiting for overlapping writers:') and
                    not task.get('waiting_for_writer')):
                tasks[-1]['error'] = None  # Historical diagnostic, no longer a live blocker.
        return {'tasks': tasks, 'scheduler': view.get('scheduler'),
                'publication': (view.get('publication') or {}).get('state'),
                'counts': dict(Counter(t['state'] for t in tasks))}

    def events(self, task, cursor, run=None):
        folder = self.run_dir(task)
        identity = str(folder.relative_to(self.root)).replace('\\', '/')
        reset = run is not None and run != identity
        events, following = read_events(folder / 'progress.jsonl', 0 if reset else cursor)
        return {'events': events, 'next': following, 'run': identity, 'reset': reset}


def make_server(root, port=8766):
    app = Console(root)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def authorized(self, writing=False):
            expected = 'http://' + self.headers.get('Host', '')
            host = self.headers.get('Host', '')
            allowed = {'127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port)}
            if host not in allowed:
                return False
            if writing and (self.headers.get('Origin') != expected or
                            self.headers.get('X-Console-Token') != app.token):
                return False
            return True

        def reply(self, value, code=200, html=False):
            data = value.encode('utf-8') if html else json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.authorized():
                return self.reply({'error': 'Invalid host'}, 403)
            url = urlsplit(self.path)
            params = parse_qs(url.query)
            try:
                if url.path == '/':
                    return self.reply(Path(__file__).with_name('console.html').read_text(encoding='utf-8'), html=True)
                if url.path == '/api/status':
                    return self.reply(app.status())
                if url.path == '/api/config':
                    value = load_config(app.root)
                    return self.reply({'config': value, 'revision': config_revision(value), 'token': app.token})
                if url.path == '/api/events':
                    return self.reply(app.events(params.get('task', [''])[0], int(params.get('cursor', ['0'])[0]),
                                                 params.get('run', [None])[0]))
                return self.reply({'error': 'Not found'}, 404)
            except (ValueError, OSError) as error:
                return self.reply({'error': str(error)}, 400)

        def do_POST(self):
            if not self.authorized(writing=True):
                return self.reply({'error': 'Invalid origin or local token'}, 403)
            if self.path != '/api/config':
                return self.reply({'error': 'Not found'}, 404)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384:
                    raise ValueError('Invalid request size')
                value = json.loads(self.rfile.read(length).decode('utf-8'))
                revision = write_config(app.root, value['config'], value['revision'])
                return self.reply({'revision': revision})
            except (ValueError, KeyError, TypeError, OSError) as error:
                return self.reply({'error': str(error)}, 400)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.console = app
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--follow', help='Follow one task, with complete per-line prefixes')
    parser.add_argument('--overview', action='store_true', help='Terminal worker overview')
    args = parser.parse_args()
    if args.follow or args.overview:
        app = Console(ROOT)
        cursor, run = -1, None
        previous_height = 0
        while True:
            if args.follow:
                page = app.events(args.follow, cursor, run)
                cursor, run = page['next'], page['run']
                for event in page['events']:
                    if event.get('kind') == 'heartbeat':
                        continue
                    prefix = '[%s %s:%s %s] ' % (args.follow, event.get('phase'), event.get('round'), event.get('kind'))
                    for line in str(event.get('message', '')).splitlines():
                        print(prefix + line, flush=True)
            else:
                view = app.status()
                lines = ['Scheduler: %s | %s' % (view['scheduler'], view['counts'])]
                for task in view['tasks']:
                    live = task['live']
                    if task['state'] in ('RUNNING', 'VERIFIED', 'PLAN_REPAIR', 'NEEDS_ARBITRATION'):
                        activity = live.get('last_activity') or {}
                        lines.append('%s | %s | %s | %s | %s' % (task['id'], task['state'], live.get('phase'),
                                     live.get('model'), str(activity.get('message', '')).replace('\n', ' ')[:100]))
                if sys.stdout.isatty():
                    # Windows console supports cursor positioning without ANSI/VT.
                    if sys.platform == 'win32':
                        import ctypes
                        from ctypes import wintypes
                        kernel = ctypes.windll.kernel32
                        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
                        kernel.GetStdHandle.restype = wintypes.HANDLE
                        kernel.SetConsoleCursorPosition.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                        kernel.SetConsoleCursorPosition(kernel.GetStdHandle(-11), 0)
                    else:
                        print('\033[H\033[J', end='')
                width = max(20, shutil.get_terminal_size((100, 30)).columns - 1)
                output = [line[:width].ljust(width) for line in lines]
                if sys.stdout.isatty():
                    output += [' ' * width] * max(0, previous_height - len(output))
                print('\n'.join(output), flush=True)
                previous_height = len(lines)
            time.sleep(1)
    else:
        server = make_server(ROOT, args.port)
        print('Goose console: http://127.0.0.1:%d (workers unchanged)' % server.server_port, flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except KeyboardInterrupt:
        pass
