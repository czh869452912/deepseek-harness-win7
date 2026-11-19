"""Qualify one frozen current candidate across Source, Native and installed apps."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
from scripts import rc022_gate_runner as lanes
from scripts import current_portable_gate as portable
from scripts import verify_release as retained
from scripts.office_runtime_inputs import office_runtime_source, verified_manifest
from scripts.qualification_inputs import tree_identity, python_identity


def git(*args, **kwargs):
    return subprocess.check_output(['git', '-C', str(kwargs.get('root', ROOT)), *args], encoding='utf-8').strip()


def candidate(source, node, allow_dirty):
    baseline = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))
    if baseline['target_upstream'] != lanes.TARGET or git('rev-parse', 'HEAD', root=source) != lanes.TARGET or git('status', '--porcelain', root=source):
        raise ValueError('Unchanged pinned current Source required')
    if subprocess.check_output([str(node), '--version'], encoding='utf-8').strip() != 'v24.9.0':
        raise ValueError('Current Source requires pinned Node 24.9.0')
    dirty = bool(git('status', '--porcelain'))
    if dirty and not allow_dirty:
        raise ValueError('Qualification requires a clean checkout; --allow-dirty is a development preview')
    return dict(product_commit=git('rev-parse', 'HEAD'), worktree_dirty=dirty)


def runtime_inputs(args):
    if not getattr(args, 'python32', None) or not getattr(args, 'site_packages32', None):
        raise ValueError('Explicit x86 runtime and approved site-packages32 are required')
    return {
        'x64': (Path(sys.base_prefix).resolve(), Path(getattr(args, 'site_packages', None) or ROOT / '.venv/Lib/site-packages').resolve()),
        'x86': (Path(args.python32).resolve(), Path(args.site_packages32).resolve()),
    }


def desktop_tools(args):
    return dict(
        x64=Path(getattr(args, 'electron64', None) or ROOT / '.goose/tools/electron-22.3.27-win32-x64/electron-v22.3.27-win32-x64.zip').resolve(),
        x86=Path(getattr(args, 'electron32', None) or ROOT / '.goose/tools/electron-22.3.27-win32-ia32/electron-v22.3.27-win32-ia32.zip').resolve(),
        nsis=Path(getattr(args, 'nsis', None) or ROOT / '.goose/tools/nsis-3.13/nsis-3.13.zip').resolve())


def installed_node_identity(source, node):
    roots = [source, node.parent, ROOT / 'node_modules'] + [ROOT / folder / 'node_modules' for folder in
        ['scripts/oracles', 'scripts/oracles/official', 'scripts/source-runtime']]
    prepared = (source / 'node_modules').resolve().parent
    if prepared != source:
        # An isolated tracked Source may reuse an existing prepared pnpm graph.
        # Workspace links can enter that original Source, so bind its full tree
        # and require the same clean pin rather than approving an arbitrary parent.
        if git('rev-parse', 'HEAD', root=prepared) != lanes.TARGET or git('status', '--porcelain', root=prepared):
            raise ValueError('Reused prepared Source must have the unchanged current pin')
        roots.append(prepared)
    # Bind installed bytes and resolution links, including absent optional links.
    # Every dependency root is explicit; links may not escape these inputs.
    return tree_identity(roots, [ROOT, source, node.parent] + [path.resolve() for path in roots],
        progress=lambda item: print('Dependency bytes: ' + str(item['files']), flush=True)
            if item['files'] % 20000 == 0 else None)


def freeze(source, node, browsers, office, runtimes, tools, source_test_node):
    value = lanes.input_identity(source, node)
    # Check copy inputs before traversing the much larger installed Node graph.
    value['python_build_inputs'] = {arch:python_identity(ROOT, runtime, site, arch)
                                    for arch, (runtime, site) in runtimes.items()}
    names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z', '--cached',
                                    '--others', '--exclude-standard']).decode('utf-8').split('\0')
    value['checkout'] = {name:lanes.digest(ROOT / name) for name in sorted(set(names))
                         if name and (ROOT / name).is_file()}
    value['browsers'] = {str(path):lanes.digest(path) for path in browsers}
    value['office'] = {architecture:verified_manifest(office_runtime_source(ROOT, office, architecture), architecture)
                       for architecture in ['x64', 'x86']}
    value['installed_node'] = installed_node_identity(source, node)
    value['desktop_tools'] = {name:dict(path=str(path), sha256=lanes.digest(path)) for name,path in tools.items()}
    observers = [path.parent for path in browsers] + [
        ROOT / '.goose/tools/electron-44.0.0-win32-x64/runtime',
        ROOT / '.goose/tools/node-22.22.2',
    ]
    value['observer_support'] = tree_identity(observers, [path.resolve() for path in observers])
    value['source_test_runtime'] = tree_identity([source_test_node.parent], [source_test_node.parent])
    return value


def desktop_lane(architecture, portable_root, output, tools, node, environment, expected_commit, expected_dirty=False):
    destination = output / ('desktop-' + architecture)
    lanes.execute([sys.executable, 'scripts/build_desktop.py', '--architecture', architecture,
        '--edition', 'standard', '--portable-dir', str(portable_root), '--output-dir', str(destination),
        '--electron-archive', str(tools[architecture]), '--nsis-archive', str(tools['nsis'])],
        ROOT, output, 'desktop-build-' + architecture, environment, 2400)
    receipt = destination / 'desktop-build.json'
    result = json.loads(receipt.read_text(encoding='utf-8'))
    if (result.get('status') != 'built' or result['portable']['product_commit'] != expected_commit
            or result['portable'].get('worktree_dirty') is not expected_dirty or len(result.get('artifacts', [])) != 1
            or len(result.get('pipePreflight', {}).get('checks', [])) != 9):
        raise ValueError('Current packaged Desktop build/preflight differs: ' + architecture)
    for artifact in result['artifacts']:
        path = destination / artifact['path']
        if path.stat().st_size != artifact['bytes'] or lanes.digest(path) != artifact['sha256']:
            raise ValueError('Desktop installer bytes changed')
    observed = destination / 'packaged-browser'
    lanes.execute([str(node), 'scripts/oracles/desktop_packaged_current.mjs',
        '--executable', str(destination / 'desktop-unpacked/DeepSeek Harness.exe'), '--output', str(observed)],
        ROOT, output, 'desktop-browser-' + architecture, environment, 360)
    observation = json.loads((observed / 'report.json').read_text(encoding='utf-8'))
    if observation.get('status') != 'qualified' or observation.get('errors') or observation.get('consoleErrors'):
        raise ValueError('Actual packaged Desktop browser failed: ' + architecture)
    # These are completed reconstructible copies. Installers and observations
    # stay bound to the exact candidate; no installation/Win7 claim is made.
    cleanup = lanes.retire_success(destination, ['desktop-unpacked', 'nsis'])
    return dict(status='passed', receipt_sha256=lanes.digest(receipt),
                browser_sha256=lanes.digest(observed / 'report.json'), artifacts=result['artifacts'], cleanup=cleanup)


def archive_path(build, architecture):
    suffix = '-x86' if architecture == 'x86' else ''
    path = build / ('dsh-win7-portable-v' + retained.PORTABLE_VERSION + suffix + '.zip')
    if not path.is_file():
        raise ValueError('Current Portable archive missing: ' + architecture)
    return path


def build_archive(architecture, runtime, site, office, output, environment):
    build = output / ('build-' + architecture)
    lanes.execute([sys.executable, 'scripts/build_portable.py', '--output-dir', str(build),
        '--architecture', architecture, '--office-runtime', str(office),
        '--python-runtime', str(runtime), '--site-packages', str(site)],
        ROOT, output, 'build-' + architecture, environment, 1200)
    archive = archive_path(build, architecture)
    return build, dict(path=str(archive), sha256=lanes.digest(archive))


def prepare_regression(output, frozen):
    regression = output / 'regression'
    regression.mkdir()
    # The retention fixture owns this nested directory and validates copies
    # against the same checkout bytes already frozen by the current gate.
    (regression / 'inputs.json').write_text(json.dumps(frozen['checkout'], indent=2), encoding='utf-8')
    return regression


def verify(args, output):
    if sys.platform != 'win32' or sys.version_info[:3] != (3, 8, 10):
        raise ValueError('Windows Python 3.8.10 required')
    if any(output.iterdir()):
        raise ValueError('Current qualification requires a fresh empty output directory')
    source = (ROOT / 'reference').resolve()
    node = Path(getattr(args, 'node', None) or shutil.which('node') or '').resolve()
    browser = Path(args.browser or os.environ.get('DSH_TEST_CHROMIUM', '')).resolve()
    browser108 = Path(args.browser108 or os.environ.get('DSH_TEST_CHROMIUM108', '')).resolve()
    if not all(path.is_file() for path in [node, browser, browser108]):
        raise ValueError('Node and both actual browsers are required')
    from scripts.browser108_gate import validate_input
    validate_input(browser108)
    environment = retained.release_environment(browser)
    environment.update(PATH=str(node.parent) + os.pathsep + environment['PATH'], DSH_TEST_CHROMIUM108=str(browser108))
    office = getattr(args, 'office_runtime', None) or os.environ.get('DSH_OFFICE_RUNTIME_INPUT_ROOT')
    if not office:
        raise ValueError('Both approved offline Office architectures are required')
    office = Path(office).resolve()
    environment['DSH_OFFICE_RUNTIME_INPUT_ROOT'] = str(office)
    runtimes, tools = runtime_inputs(args), desktop_tools(args)
    environment['DSH_TEST_X86_PYTHON'] = str(runtimes['x86'][0] / 'python.exe')
    old_path = os.environ['PATH']; os.environ['PATH'] = environment['PATH']
    report = dict(result='failed', publishable=False, target_upstream=lanes.TARGET, stages={},
        windows7_acceptance=False, installation_acceptance=False,
        scope='One candidate: complete Python collection, explicit current Source/paired roster, fresh x64/x86 extracted SDK/Office/metadata/original browsers/application cold recovery, and packaged Desktop/Standard installers. Win7, AIO servicing and administrator installation remain separately qualified.')
    selected = before = None
    def checkpoint():
        (output / 'current-progress.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    try:
        # Install/build inputs BEFORE freezing them; preparation is not evidence.
        if args.prepare:
            retained.prepare_node_dependencies(output, environment)
        plan = lanes.load_plan()
        test_node = lanes.source_test_runtime(plan, getattr(args, 'source_test_node', None))
        selected = candidate(source, node, args.allow_dirty); report.update(selected)
        print('Freezing actual prepared dependencies and build runtimes', flush=True)
        before = freeze(source, node, [browser, browser108], office, runtimes, tools, test_node)
        inputs = output / 'inputs.json'; inputs.write_text(json.dumps(before, indent=2), encoding='utf-8')
        report.update(input_manifest_sha256=lanes.digest(inputs), plan_sha256=lanes.digest(lanes.PLAN))
        checkpoint()
        # Mandatory Portable smoke cases must execute this candidate's bundled
        # Python, not skip because the unrelated legacy dist directory is absent.
        # Keep this exact archive for the later extracted and Desktop consumers.
        build64, archive64 = build_archive('x64', *runtimes['x64'], office, output, environment)
        environment['DSH_TEST_PORTABLE_ROOT'] = str(build64 / 'dsh-win7-portable')
        report['stages']['build-x64'] = dict(status='passed', archive=archive64)
        checkpoint()
        # The complete Python collection belongs to this one gate, with no
        # duplicate full pytest pass scheduled immediately beforehand.
        regression = prepare_regression(output, before)
        retained.run_python_regression(sys.executable, regression, environment, timeout=args.regression_timeout, maxfail=0)
        report['stages']['regression'] = dict(status='passed', **retained.validate_regression(regression / 'pytest.xml'))
        checkpoint()
        for lane in ['source', 'paired']:
            destination = output / lane; destination.mkdir()
            if lane == 'source': rows = lanes.source_lane(plan, source, test_node, destination, environment)
            else: rows = lanes.paired_lane(plan, source, node, browser108, destination, environment)
            report['stages'][lane] = dict(status='passed', rows=rows); checkpoint()
        archives = {}
        for architecture, (runtime, site) in runtimes.items():
            if architecture == 'x64':
                build, identity = build64, archive64
            else:
                build, identity = build_archive(architecture, runtime, site, office, output, environment)
            archive = archive_path(build, architecture)
            if lanes.digest(archive) != identity['sha256']:
                raise ValueError('Frozen built archive changed before qualification: ' + architecture)
            archives[architecture] = identity
            result = portable.qualify(SimpleNamespace(archive=archive, output=output / ('extracted-' + architecture),
                source=source, node=node, browser=browser, browser108=browser108, architecture=architecture,
                expected_commit=selected['product_commit']))
            if result.get('status') != 'passed' or result.get('inputs_unchanged') is not True:
                raise ValueError('Actual extracted qualification failed: ' + architecture)
            report['stages']['extracted-' + architecture] = dict(status='passed', archive=archives[architecture])
            checkpoint()
            report['stages']['desktop-' + architecture] = desktop_lane(architecture, build / 'dsh-win7-portable',
                output, tools, node, environment, selected['product_commit'], selected['worktree_dirty'])
            removed = lanes.remove_owned(build / 'dsh-win7-portable')
            (build / 'cleanup.json').write_text(json.dumps(dict(bytes_removed=removed, retained=archives[architecture]), indent=2), encoding='utf-8')
            checkpoint()
        report.update(archives=archives, result='development-preview' if selected['worktree_dirty'] else 'passed',
                      publishable=not selected['worktree_dirty'])
    except BaseException as error:
        report.update(result='failed', publishable=False, failure=str(error))
        raise
    finally:
        try:
            if before is not None:
                print('Rechecking frozen dependency bytes', flush=True)
                report['inputs_unchanged'] = before == freeze(source, node, [browser, browser108], office, runtimes, tools, test_node)
                report['candidate_unchanged'] = candidate(source, node, True) == selected
                if not report['inputs_unchanged'] or not report['candidate_unchanged']:
                    report.update(result='failed', publishable=False, failure='Frozen qualification inputs changed')
        except BaseException as error:
            report.update(result='failed', publishable=False, freeze_failure=str(error))
        finally:
            os.environ['PATH'] = old_path; checkpoint()
        if report['result'] == 'failed' and not sys.exc_info()[0]:
            raise ValueError(report.get('failure', report.get('freeze_failure')))
    return report
