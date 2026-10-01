"""Native source-project export, distinct from upstream JavaScript execution.

The package descriptor is written last: an interrupted project cannot be
installed. Files are created through the active FS service without overwriting.
"""
import hashlib
import inspect
import json
import os
import re
import stat
import zipfile

from dsh.boot.python_package import inside, package_name, relative_parts, read_descriptor, validate_sources
from dsh.boot.python_plugins import MAX_BYTES, MAX_FILES, reparse
from dsh.extensions.packaged_host import host_handler_service
from dsh.extensions.inspect_registry import _throw_if_aborted

EXPORT_RECORD = 'dsh-export.json'


def json_text(value):
    return json.dumps(value, ensure_ascii=True, indent=2) + '\n'


def project_files(package, pid, name, version, placement, services, license_name, license_text):
    package_name(name)
    if name.startswith('@deepseek-ai/'):
        raise ValueError('exports must use an author-owned package identity')
    if not isinstance(version, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[a-zA-Z0-9]+(?:[.-][a-zA-Z0-9]+)*)?(?:\+[a-zA-Z0-9]+(?:[.-][a-zA-Z0-9]+)*)?', version):
        raise ValueError('export version must be a semantic version')
    if placement not in ('host', 'session'):
        raise ValueError('placement must be host or session')
    if not isinstance(services, (list, tuple)) or any(type(key) is not str or not key for key in services):
        raise ValueError('isolateServices must be an array of service names')
    if not license_name.strip() or not license_text.strip():
        raise ValueError('export requires an explicit license and licenseText')
    code = package['code']
    files = {}
    origin = dict(formatVersion=1, pluginId=pid, packageId=package['packageId'],
        name=package['name'], purpose=package['purpose'], placement=placement,
        sourceSha256={half: hashlib.sha256(text.encode('utf-8')).hexdigest() for half, text in code.items()},
        requiresClientBuild='client' in code)
    row = dict(id='python-export-' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:24], name=name)
    if placement == 'session':
        row['isolate'] = {key: True for key in [host_handler_service(name)] + list(services)}
    files['preset.fragment.yml'] = json_text([row] if placement == 'session' else [])
    files['cordis.patch.yml'] = json_text([dict(insert=[row])] if placement == 'host' else [])
    if 'host' in code:
        # Keep the exact source body, including its original line endings.
        files['python/exported/host.body.py'] = code['host']
        files['python/exported/plugin.py'] = (
            'import os\nfrom dsh.plugin_api import python_host_source\n\n'
            'plugin = python_host_source(os.path.join(os.path.dirname(__file__), "host.body.py"), ' + repr(name) + ')\n')
    else:
        files['python/exported/plugin.py'] = 'def plugin(ctx, config=None):\n    pass\n'
    if 'client' in code:
        files['client/source.js'] = code['client']
    files['LICENSE'] = license_text
    files['tests/README.md'] = ('Add behavior and unload regression tests for this plugin before publishing.\n'
        'The exported source retains its service dependencies; test against a clean profile.\n')
    files['README.md'] = ('# ' + name + '\n\n' + package['purpose'] + '\n\n'
        'Native Python 3.8.10 Host source project; experimental Plugin API 1.\n'
        'Origin: ' + pid + '/' + package['packageId'] + '. Placement: ' + placement + '.\n\n'
        'Edit python/exported/host.body.py, add behavioral tests, and increment package.json version.\n'
        'Pack: dsh plugin --profile web pack <project> <output.zip>\n'
        'Only dsh.sourceExport.files are packed. Add reviewed tests/resources to that explicit list.\n'
        'Install: dsh plugin --profile web add <project-or-zip> (stop the profile first).\n'
        'For session placement, append preset.fragment.yml rows to a USER agent.cordis.yml;\n'
        'installation does not mount session tools on the Host or change built-in presets.\n'
        'Sessions selecting the same preset share its standing plugin instances, as upstream does.\n'
        'harness.handle methods are available through the ' + host_handler_service(name) + ' service call(method, args).\n'
        'This source project grants only the permissions stated in LICENSE; review dependencies and code before activation.\n'
        + ('\nClient source is preserved. Before pack/install, run:\n'
           'dsh plugin --profile web build <project>\n'
           'Build wraps plain JavaScript using the pinned browser evaluator; no TS/JSX compiler or Node runtime is used.\n'
           'Rebuild after source edits. Syntax failures are reported during original browser activation.\n'
           'Host placement is supported; session Client ownership remains pending and build refuses that placement.\n' if 'client' in code else ''))
    manifest = dict(name=name, version=version, license=license_name,
        dsh=dict(bundle=dict(patch='cordis.patch.yml'), python=dict(apiVersion=1,
            sourceRoot='python', entry='exported.plugin:plugin', minPythonVersion=[3, 8, 10],
            minHostVersion=[0, 1, 0], dependencies=[]), sourceExport=dict(record=EXPORT_RECORD,
                files=[EXPORT_RECORD] + list(files) + ['package.json'])))
    # The claim is created first. Descriptor publication is the commit point.
    files = dict([(EXPORT_RECORD, json_text(origin))] + list(files.items()))
    files['package.json'] = json_text(manifest)
    if len(files) > MAX_FILES or sum(len(text.encode('utf-8')) for text in files.values()) > MAX_BYTES:
        raise ValueError('export exceeds installation size limits')
    return files


async def export_project(ctx, args, execution):
    agent, signal = execution.agent, execution.signal
    _throw_if_aborted(signal)
    if agent is None or getattr(agent, 'session', None) is None:
        raise ValueError('source export requires an Agent-backed session')
    package = ctx.get('dynamicCordisRunner').inspectPackage(agent, args['pluginId'], args['packageId'])
    files = project_files(package, args['pluginId'], args['name'], args['version'], args['placement'],
                          args.get('isolateServices', []), args['license'], args['licenseText'])
    fs = ctx.get('fs')
    if fs is None:
        raise ValueError('source export requires the active fs service')
    output = args['directory'].replace('\\', '/')
    relative_parts(output)
    header = agent.session.header
    cwd = header.get('cwd') if isinstance(header, dict) else header.cwd
    root = await fs.resolve(output, dict(cwd=cwd, signal=signal))
    workspace = await fs.resolve('.', dict(cwd=cwd, signal=signal))
    if os.path.normcase(os.path.commonpath([root.targetKey, workspace.targetKey])) != os.path.normcase(workspace.targetKey):
        raise ValueError('export directory must be inside the session workspace')
    installation = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for owned in ('dsh', 'apps', 'packages', 'reference', 'dist'):
        protected = os.path.join(installation, owned)
        try:
            contained = os.path.normcase(os.path.commonpath([root.targetKey, protected])) == os.path.normcase(protected)
        except ValueError:
            contained = False
        if contained:
            raise ValueError('export cannot modify installation-owned code or presets')
    if await fs.lstat(root.displayPath, signal=signal) is not None:
        raise ValueError('export directory must not already exist')
    policy = None
    if getattr(fs, 'sandboxMode', None) is not None:
        provider = ctx.get('sandboxPolicy')
        if provider is None:
            raise ValueError('sandboxPolicy is required by the active fs service')
        policy = provider.resolve(dict(session=agent.session))
        if inspect.isawaitable(policy):
            policy = await policy
    for relative, text in files.items():
        _throw_if_aborted(signal)
        target = await fs.resolve(os.path.join(root.displayPath, *relative_parts(relative)), dict(signal=signal))
        if os.path.normcase(os.path.commonpath([root.targetKey, target.targetKey])) != os.path.normcase(root.targetKey):
            raise ValueError('export file escapes its project directory')
        await fs.writeText(target, text, dict(kind='createIfAbsent'), signal=signal, sandbox_policy=policy)
    return dict(name=args['name'], version=args['version'], directory=output,
                pluginId=args['pluginId'], packageId=args['packageId'], placement=args['placement'],
                files=list(files), requiresClientBuild='client' in package['code'])


def release_files(project):
    """Validate the explicit project release set without executing source."""
    manifest = read_descriptor(project)[0]
    dsh = manifest['dsh']
    release = dsh.get('sourceExport', dsh.get('release', {})).get('files')
    if not isinstance(release, list) or not release or len(set(release)) != len(release):
        raise ValueError('pack requires an explicit dsh.sourceExport.files or dsh.release.files release list')
    entries, seen, total = [], set(), 0
    if reparse(project):
        raise ValueError('source project must not be a link or junction')
    for relative in release:
        path = inside(project, relative)
        key = relative.casefold()
        if key in seen:
            raise ValueError('duplicate release path: ' + relative)
        seen.add(key)
        current = os.path.abspath(project)
        for part in relative_parts(relative):
            current = os.path.join(current, part)
            if not os.path.exists(current) or reparse(current):
                raise ValueError('release file is missing or linked: ' + relative)
        if not stat.S_ISREG(os.stat(path).st_mode) or path.lower().endswith(('.dll', '.pyd', '.so', '.exe', '.whl')):
            raise ValueError('release file is unsupported: ' + relative)
        total += os.path.getsize(path)
        if len(entries) >= MAX_FILES or total > MAX_BYTES:
            raise ValueError('release exceeds installation size limits')
        entries.append((relative, path))
    required = {'package.json', dsh['bundle']['patch'], 'README.md', 'LICENSE'}
    if 'sourceExport' in dsh:
        required.add(dsh['sourceExport']['record'])
    required.update(dsh.get('webArtifacts', {}).get('files', {}))
    for root, dirs, files in os.walk(inside(project, manifest['dsh']['python']['sourceRoot'])):
        dirs[:] = [name for name in dirs if name != '__pycache__']
        required.update(os.path.relpath(os.path.join(root, file), project).replace('\\', '/') for file in files if file.endswith('.py'))
    if not required.issubset(release):
        raise ValueError('release list omits required descriptor, source, Web artifacts, README or LICENSE files')
    validate_sources(project)
    return manifest, entries


def pack_project(project, destination):
    """Pack a reviewed project tree; never invoke Node, pip, or package scripts."""
    manifest, entries = release_files(project)
    destination = os.path.abspath(destination)
    try:
        inside_project = os.path.normcase(os.path.commonpath([os.path.realpath(project), os.path.realpath(destination)])) == os.path.normcase(os.path.realpath(project))
    except ValueError:
        inside_project = False  # A Windows output on another drive is external.
    if inside_project:
        raise ValueError('ZIP output must be outside the source project')
    with open(destination, 'xb') as stream:
        try:
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                for relative, path in entries:
                    archive.write(path, relative)
        except BaseException:
            stream.close()
            os.unlink(destination)
            raise
    return manifest['name']
