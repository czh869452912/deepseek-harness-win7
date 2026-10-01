"""Real TLS acquisition feeds the same native store, boot and rollback paths."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from apps.cli import plugin as cli
from apps.cli.args import HELP_TEXT, parse_dsh_args
from dsh.boot import python_plugin_acquisition as acquisition
from dsh.boot import python_plugin_versions as versions
from dsh.boot import python_plugins as store
from dsh.boot.profile import read_profile_manifest
from dsh.boot.profile_boot import INSTALL_ANCHOR
from test_python_plugin_distribution import profile, boot, close, echo, EXAMPLE, PACKAGE, ROOT
from test_python_plugin_versions import source_version, zip_source, record, installed


@pytest.fixture
def release_server(tmp_path, monkeypatch):
    certificate = Path(__file__).parent / 'fixtures/tls/localhost-cert.pem'
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificate), str(certificate.with_name('localhost-key.pem')))
    default_context = ssl._create_default_https_context
    monkeypatch.setattr(ssl, '_create_default_https_context', lambda: ssl.create_default_context(cafile=str(certificate)))
    archive = zip_source(EXAMPLE, tmp_path / 'release.zip')
    state = dict(payload=archive.read_bytes(), requests=[], release=threading.Event())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            state['requests'].append(path)
            redirects = {'/release': '/asset.zip?token=fixture-redirect-secret',
                         '/downgrade': 'http://localhost:{}/trap'.format(self.server.server_port),
                         '/credentials': 'https://user:secret@localhost:{}/asset.zip'.format(self.server.server_port),
                         '/loop': '/loop'}
            if path in redirects:
                self.send_response(302)
                self.send_header('Location', redirects[path])
                self.end_headers()
                return
            if path == '/missing':
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(206 if path == '/range' else 200)
            if path == '/encoded':
                self.send_header('Content-Encoding', 'gzip')
            length = len(state['payload'])
            if path == '/oversized':
                length = acquisition.MAX_BYTES + 1
            elif path == '/partial':
                length += 17
            if path != '/unbounded':
                self.send_header('Content-Length', 'invalid' if path == '/bad-length' else str(length))
            self.end_headers()
            if path == '/slow':
                state['release'].wait(5)
            try:
                self.wfile.write(state['payload'])
            except OSError:
                pass  # Expected peer close for failed/limited acquisition.

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.update(url='https://localhost:{}'.format(server.server_port), certificate=certificate,
                 default_context=default_context)
    try:
        yield state
    finally:
        state['release'].set()
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


def digest(state):
    return hashlib.sha256(state['payload']).hexdigest()


def command(state, action='add', endpoint='/release'):
    return [action, state['url'] + endpoint, '--sha256', digest(state)]


@pytest.mark.asyncio
@pytest.mark.parametrize('upgrade_source', ['https', 'local'])
async def test_tls_install_boot_upgrade_offline_rollback_and_provenance(profile, tmp_path, release_server, monkeypatch, upgrade_source):
    home, directory = profile
    state = release_server
    first_digest = digest(state)
    assert cli.run_plugin('python-test', command(state, endpoint='/release?access_token=fixture-origin-secret')) == 0
    original = dict(kind='https-zip', url=state['url'] + '/release', sha256=first_digest, bytes=len(state['payload']))
    assert record(directory)['acquisition'] == original
    result = await boot(home)
    try:
        assert await echo(result['ctx'], 'TLS') == 'Python echo: TLS'
    finally:
        await close(result)
    source = source_version(tmp_path)
    state['payload'] = zip_source(source, tmp_path / 'v2.zip').read_bytes()
    args = command(state, 'upgrade') if upgrade_source == 'https' else ['upgrade', str(source)]
    assert cli.run_plugin('python-test', args) == 0
    second = record(directory)
    assert second['history'][0]['acquisition'] == original
    if upgrade_source == 'https':
        assert second['acquisition']['sha256'] == digest(state)
    else:
        assert 'acquisition' not in second
    result = await boot(home)
    try:
        assert await echo(result['ctx'], 'TLS') == 'Version two: TLS'
    finally:
        await close(result)
    requests = state['requests'][:]
    def no_network(*args, **kwargs):
        raise AssertionError('offline version operations must not fetch a source')
    monkeypatch.setattr(acquisition, 'build_opener', no_network)
    assert cli.run_plugin('python-test', ['rollback', PACKAGE, '0.1.0']) == 0
    assert record(directory)['acquisition'] == original
    listing = versions.versions(str(directory), PACKAGE)
    assert listing['versions'][0]['acquisition'] == original
    assert state['requests'] == requests
    assert 'fixture-origin-secret' not in json.dumps(record(directory))
    assert 'fixture-redirect-secret' not in json.dumps(record(directory))
    assert 'dsh-plugin-download-' not in json.dumps(record(directory))
    result = await boot(home)
    try:
        assert await echo(result['ctx'], 'offline') == 'Python echo: offline'
    finally:
        await close(result)
    assert cli.run_plugin('python-test', ['rollback', PACKAGE]) == 0
    if upgrade_source == 'https':
        assert record(directory)['acquisition']['sha256'] == digest(state)
    else:
        assert 'acquisition' not in record(directory)
    assert state['requests'] == requests
    assert cli.run_plugin('python-test', ['remove', PACKAGE]) == 0
    assert not installed(directory).exists()


def test_canonical_cli_tls_acquisition_without_system_package_tools(profile, release_server):
    home, directory = profile
    environment = dict(os.environ, SSL_CERT_FILE=str(release_server['certificate']),
                       PATH=str(Path(sys.executable).parent))
    run = subprocess.run([sys.executable, str(ROOT / 'dsh.py'), 'plugin', '--profile', 'python-test']
                         + command(release_server), env=environment, cwd=str(home),
                         capture_output=True, encoding='utf-8', timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
    assert PACKAGE in run.stdout and record(directory)['acquisition']['sha256'] == digest(release_server)
    assert read_profile_manifest('dsh', str(directory))['dsh']['profile']['bundles'] == [PACKAGE]


def test_new_profile_uses_native_template_after_verified_transfer(tmp_path, release_server, monkeypatch):
    home = tmp_path / 'fresh-home'
    monkeypatch.setenv('DSH_HOME', str(home))
    monkeypatch.setattr(cli, 'run_pnpm', lambda *args: pytest.fail('HTTPS acquisition must use the native store'))
    assert cli.run_plugin('web', command(release_server)) == 0
    manifest = read_profile_manifest('dsh', str(home / 'profiles/web'))
    assert PACKAGE in manifest['dsh']['profile']['bundles']
    assert manifest['dsh']['pythonPlugins'][PACKAGE]['acquisition']['sha256'] == digest(release_server)


def test_author_pack_hash_can_pin_the_actual_release_install(profile, tmp_path, release_server, capsys):
    _, directory = profile
    source = source_version(tmp_path)
    descriptor = source / 'package.json'
    manifest = json.loads(descriptor.read_text(encoding='utf-8'))
    manifest['dsh']['release'] = dict(formatVersion=1, files=sorted(path.relative_to(source).as_posix()
        for path in source.rglob('*') if path.is_file() and '__pycache__' not in path.parts))
    descriptor.write_text(json.dumps(manifest), encoding='utf-8')
    archive = tmp_path / 'published.zip'
    assert cli.run_plugin('python-test', ['pack', str(source), str(archive)]) == 0
    release_server['payload'] = archive.read_bytes()
    assert 'archive SHA-256 ' + digest(release_server) in capsys.readouterr().out
    assert cli.run_plugin('python-test', command(release_server)) == 0
    assert record(directory)['acquisition']['sha256'] == digest(release_server)


@pytest.mark.parametrize('failure', ['syntax', 'dependencies', 'identity', 'publication'])
def test_downloaded_candidate_failure_preserves_installed_generation(profile, tmp_path, release_server, monkeypatch, failure):
    _, directory = profile
    cli.run_plugin('python-test', command(release_server))
    before = (directory / 'package.json').read_bytes()
    previous = (installed(directory) / 'python/echo/plugin.py').read_bytes()
    source = source_version(tmp_path)
    descriptor = source / 'package.json'
    manifest = json.loads(descriptor.read_text(encoding='utf-8'))
    if failure == 'syntax':
        (source / 'python/echo/plugin.py').write_text('def broken(:\n', encoding='utf-8')
    elif failure == 'dependencies':
        manifest['dsh']['python']['dependencies'] = ['unsupported-library']
    elif failure == 'identity':
        manifest['name'] = '@deepseek-ai/dsh-tools'
    else:
        original_write = store.atomic_bytes
        def fail_publication(path, body):
            if Path(path) == directory / 'package.json':
                raise OSError('fixture publication failure')
            return original_write(path, body)
        monkeypatch.setattr(store, 'atomic_bytes', fail_publication)
    descriptor.write_text(json.dumps(manifest), encoding='utf-8')
    release_server['payload'] = zip_source(source, tmp_path / 'invalid.zip').read_bytes()
    temporary_paths = []
    original_directory = acquisition.tempfile.TemporaryDirectory
    def observe(*args, **kwargs):
        temporary = original_directory(*args, **kwargs)
        temporary_paths.append(Path(temporary.name))
        return temporary
    monkeypatch.setattr(acquisition.tempfile, 'TemporaryDirectory', observe)
    with pytest.raises(OSError if failure == 'publication' else ValueError):
        cli.run_plugin('python-test', command(release_server, 'upgrade'))
    assert (directory / 'package.json').read_bytes() == before
    assert (installed(directory) / 'python/echo/plugin.py').read_bytes() == previous
    assert temporary_paths and all(not path.exists() for path in temporary_paths)
    assert not (directory / store.JOURNAL).exists()


@pytest.mark.asyncio
async def test_download_cannot_replace_a_running_profile(profile, tmp_path, release_server):
    home, directory = profile
    cli.run_plugin('python-test', command(release_server))
    source = source_version(tmp_path)
    release_server['payload'] = zip_source(source, tmp_path / 'v2.zip').read_bytes()
    before = (directory / 'package.json').read_bytes()
    result = await boot(home)
    try:
        with pytest.raises(RuntimeError, match='profile is in use'):
            cli.run_plugin('python-test', command(release_server, 'upgrade'))
        assert await echo(result['ctx'], 'active') == 'Python echo: active'
        assert (directory / 'package.json').read_bytes() == before
    finally:
        await close(result)


@pytest.mark.parametrize('endpoint, message', [
    ('/missing', 'status 404'), ('/range', 'complete 200'), ('/loop', 'status 302'),
    ('/downgrade', 'requires HTTPS'), ('/credentials', 'URL credentials'),
    ('/encoded', 'content encoding'), ('/oversized', 'byte limit'),
    ('/bad-length', 'Content-Length'), ('/partial', 'incomplete'),
])
def test_failed_transfer_preserves_existing_profile_and_package(profile, release_server, endpoint, message):
    _, directory = profile
    cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    before = (directory / 'package.json').read_bytes()
    source = (installed(directory) / 'python/echo/plugin.py').read_bytes()
    with pytest.raises(ValueError, match=message):
        cli.run_plugin('python-test', command(release_server, 'upgrade', endpoint))
    assert (directory / 'package.json').read_bytes() == before
    assert (installed(directory) / 'python/echo/plugin.py').read_bytes() == source
    assert '/trap' not in release_server['requests']
    if endpoint == '/credentials':
        assert '/asset.zip' not in release_server['requests']


@pytest.mark.parametrize('failure', ['hash', 'not-zip', 'untrusted-tls', 'stream-limit', 'timeout', 'deadline'])
def test_bounded_acquisition_cleans_temporary_files_before_profile_creation(tmp_path, monkeypatch, release_server, failure):
    home = tmp_path / 'new-home'
    monkeypatch.setenv('DSH_HOME', str(home))
    real_directory = acquisition.tempfile.TemporaryDirectory
    directories = []
    def observed_directory(*args, **kwargs):
        result = real_directory(*args, **kwargs)
        directories.append(Path(result.name))
        return result
    monkeypatch.setattr(acquisition.tempfile, 'TemporaryDirectory', observed_directory)
    endpoint, expected = '/asset.zip', digest(release_server)
    if failure == 'hash':
        expected = '0' * 64
    elif failure == 'not-zip':
        release_server['payload'] = b'not a release archive'
        expected = digest(release_server)
    elif failure == 'untrusted-tls':
        monkeypatch.setattr(ssl, '_create_default_https_context', release_server['default_context'])
    elif failure == 'stream-limit':
        endpoint = '/unbounded'
        monkeypatch.setattr(acquisition, 'MAX_BYTES', 32)
    elif failure == 'timeout':
        endpoint = '/slow'
        monkeypatch.setattr(acquisition, 'REQUEST_TIMEOUT', 0.15)
    else:
        ticks = iter((0, 0, 100))
        monkeypatch.setattr(acquisition, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
        monkeypatch.setattr(acquisition, 'CHUNK_BYTES', 16)
    with pytest.raises(ValueError):
        cli.run_plugin('new-profile', ['add', release_server['url'] + endpoint, '--sha256', expected])
    assert directories and all(not path.exists() for path in directories)
    assert not (home / 'profiles/new-profile/package.json').exists()


@pytest.mark.parametrize('args', [
    ['add', 'https://example.invalid/release.zip'],
    ['add', 'https://example.invalid/release.zip', '--sha256', 'short'],
    ['add', 'http://example.invalid/release.zip', '--sha256', '0' * 64],
    ['add', 'ftp://example.invalid/release.zip', '--sha256', '0' * 64],
    ['add', 'https://user:secret@example.invalid/release.zip', '--sha256', '0' * 64],
    ['add', 'https://example.invalid/release.zip#fragment', '--sha256', '0' * 64],
    ['add', 'https://example.invalid:invalid/release.zip', '--sha256', '0' * 64],
    ['add', 'https://example.invalid/\nrelease.zip', '--sha256', '0' * 64],
    ['upgrade', 'https://example.invalid/release.zip', '--sha256', '0' * 64],
])
def test_bad_native_acquisition_arguments_never_fall_back_or_fetch(tmp_path, monkeypatch, args):
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'home'))
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid native acquisition must not fetch or use pnpm')
    monkeypatch.setattr(acquisition, 'build_opener', forbidden)
    monkeypatch.setattr(cli, 'run_pnpm', forbidden)
    with pytest.raises(ValueError):
        cli.run_plugin('new-profile', args)
    assert not (tmp_path / 'home/profiles/new-profile/package.json').exists()


def test_launcher_leaves_acquisition_arguments_with_selected_plugin_app():
    args = ['add', 'https://example.invalid/release.zip', '--sha256', 'f' * 64]
    invocation = parse_dsh_args(['plugin', '--profile', 'web'] + args)
    assert invocation == dict(mode='plugin', profile='web', args=args)
    assert '--sha256 <digest>' in HELP_TEXT


def test_acquisition_record_cannot_describe_another_archive(profile, tmp_path):
    _, directory = profile
    source = zip_source(EXAMPLE, tmp_path / 'source.zip')
    metadata = dict(kind='https-zip', url='https://example.invalid/release.zip', sha256='0' * 64,
                    bytes=source.stat().st_size)
    before = (directory / 'package.json').read_bytes()
    with pytest.raises(ValueError, match='differs from its source archive'):
        store.install(str(directory), str(source), INSTALL_ANCHOR, acquisition=metadata)
    assert (directory / 'package.json').read_bytes() == before
