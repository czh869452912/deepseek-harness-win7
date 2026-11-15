"""Native association metadata and registered-handler launches on Python 3.8."""
import asyncio
import base64
import json
import math
import os
from pathlib import Path
import re
import tempfile

from dsh.cordis.text import trim_js
from dsh.host.native_command_current import facts, native_file_manager, translate

RESOURCES = Path(__file__).with_name('resources')


def parse_native_file_applications(value):
    if not isinstance(value, list):
        raise ValueError('Invalid native application list')
    result = []
    for entry in value:
        if (not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not entry['id']
                or not isinstance(entry.get('name'), str) or type(entry.get('default')) is not bool
                or 'icon' not in entry or not (entry['icon'] is None or isinstance(entry['icon'], str)
                    and re.fullmatch(r'data:image/(?:png|svg\+xml);base64,[A-Za-z0-9+/=]+', entry['icon']))):
            raise ValueError('Invalid native application entry')
        result.append({key: entry[key] for key in ('id', 'name', 'default', 'icon')})
    return result


async def windows_file_applications(path, application, signal, run):
    encoded_path = base64.b64encode(path.encode('utf-8')).decode('ascii')
    encoded_app = base64.b64encode(('' if application is None else application).encode('utf-8')).decode('ascii')
    code = (RESOURCES / 'file_associations.cs').read_text(encoding='utf-8')
    # The Shell adapter is byte-preserved Source C#. PS2 lacks ConvertTo-Json;
    # its .NET JavaScriptSerializer fallback preserves the same four wire fields.
    query = """if (Get-Command ConvertTo-Json -ErrorAction SilentlyContinue) {
  ConvertTo-Json -InputObject @([DshFileAssociations]::List($path)) -Depth 4 -Compress
} else {
  Add-Type -AssemblyName System.Web.Extensions
  $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
  $serializer.Serialize(@([DshFileAssociations]::List($path)))
}""" if application is None else '[DshFileAssociations]::Open($path, $application)'
    script = """$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -ReferencedAssemblies System,System.Core,System.Drawing -TypeDefinition @'
""" + code + "\n'@\n" + "$path = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{}'))\n".format(encoded_path) + "$application = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{}'))\n".format(encoded_app) + query + '\n'
    with tempfile.TemporaryDirectory(prefix='dsh-native-command-') as directory:
        script_path = Path(directory) / 'associations.ps1'
        script_path.write_text('\ufeff' + script, encoding='utf-8')
        result = await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-STA', '-ExecutionPolicy', 'Bypass', '-File', str(script_path)], signal)
        return result['stdout']


def desktop_entry_fields(text):
    fields, main = {}, False
    for line in re.split(r'\r?\n', text):
        line = trim_js(line)
        if line.startswith('['):
            main = line == '[Desktop Entry]'
            continue
        if not main or line.startswith('#'):
            continue
        separator = line.find('=')
        if separator > 0:
            fields[trim_js(line[:separator])] = trim_js(line[separator+1:])
    return fields


def desktop_data_directories(env):
    return [env.get('XDG_DATA_HOME', os.path.join(env.get('HOME', str(Path.home())), '.local', 'share'))] + [part for part in env.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if part]


def desktop_file(root, identity, directory=None):
    directory = root if directory is None else directory
    try:
        entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
    except OSError:
        return None
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False) and os.path.relpath(entry.path, root).replace(os.sep, '-') == identity:
            return entry.path
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            found = desktop_file(root, identity, entry.path)
            if found is not None:
                return found
    return None


def desktop_icon(name, directories):
    def read(path):
        kind = 'image/png' if path.endswith('.png') else 'image/svg+xml' if path.endswith('.svg') else None
        try:
            if kind is not None and Path(path).is_file():
                return 'data:{};base64,{}'.format(kind, base64.b64encode(Path(path).read_bytes()).decode('ascii'))
        except OSError:
            pass
        return None
    if os.path.isabs(name):
        return read(name)
    for directory in directories:
        candidates = [os.path.join(directory, 'icons', 'hicolor', size, 'apps', name+'.'+extension)
                      for size in ('512x512','256x256','128x128','64x64','48x48','32x32') for extension in ('png','svg')]
        candidates += [os.path.join(directory, 'icons', 'hicolor', 'scalable', 'apps', name+'.svg')]
        candidates += [os.path.join(directory, 'pixmaps', name+'.'+extension) for extension in ('png','svg')]
        for path in candidates:
            value = read(path)
            if value is not None:
                return value
    return None


async def linux_file_applications(path, signal, run, env):
    info = await run('gio', ['info', '-a', 'standard::content-type', path], signal)
    mime = re.search(r'standard::content-type:\s*(\S+)', info['stdout'])
    if mime is None:
        raise RuntimeError('GIO did not identify the file content type')
    result = await run('env', ['LC_ALL=C', 'gio', 'mime', mime.group(1)], signal)
    preferred = re.search(r'^Default application.*:\s*(.+\.desktop)\s*$', result['stdout'], re.M)
    preferred = preferred.group(1) if preferred is not None else None
    ids = ([] if preferred is None else [preferred]) + [trim_js(line) for line in re.split(r'\r?\n', result['stdout']) if re.search(r'^\s+.*\.desktop\s*$', line)]
    ids = list(dict.fromkeys(ids)); directories = desktop_data_directories(env)
    locale = re.sub(r'\..*$', '', env.get('LC_ALL', env.get('LC_MESSAGES', env.get('LANG', ''))))
    applications = []
    loop = asyncio.get_running_loop()
    for identity in ids:
        signal.throwIfAborted()
        entry = None
        for directory in directories:
            entry = await loop.run_in_executor(None, desktop_file, os.path.join(directory, 'applications'), identity)
            if entry is not None:
                break
        if entry is None:
            continue
        text = await loop.run_in_executor(None, lambda: Path(entry).read_text(encoding='utf-8', errors='replace'))
        fields = desktop_entry_fields(text)
        name = fields.get('Name['+locale+']', fields.get('Name['+re.sub(r'_.*', '', locale)+']', fields.get('Name')))
        if name is None or fields.get('Hidden') == 'true':
            continue
        icon = await loop.run_in_executor(None, desktop_icon, fields['Icon'], directories) if 'Icon' in fields else None
        applications.append(dict(id=entry, name=name, default=identity==preferred, icon=icon))
    return applications


def parse_mac_applications(value):
    result = parse_native_file_applications(value)
    for entry, parsed in zip(value, result):
        for key in ('bundle', 'version'):
            field = entry.get(key)
            if field is not None and not isinstance(field, str):
                raise ValueError('Invalid native application entry')
            parsed[key] = field or None
    return result


def compare_versions(left, right):
    if left is None or right is None:
        return 0 if left == right else -1 if left is None else 1
    def number(value):
        try:
            # Number() accepts whitespace, radix prefixes, infinities and exponents.
            raw = trim_js(value)
            result = float(int(raw, 0)) if raw.lower().startswith(('0x','0o','0b')) else float(raw or '0')
            return 0 if math.isnan(result) else result
        except ValueError:
            return 0
    a, b = left.split('.'), right.split('.')
    for index in range(max(len(a), len(b))):
        delta = number(a[index] if index < len(a) else '') - number(b[index] if index < len(b) else '')
        if delta != 0:
            return delta
    return 0


def dedupe_mac_applications(applications):
    order, groups = [], {}
    for app in applications:
        key = None if app['bundle'] is None else (app['bundle'], app['name'])
        if key is None or key not in groups:
            if key is not None:
                groups[key] = len(order)
            order.append(app)
            continue
        index = groups[key]; held = order[index]
        if not held['default'] and (app['default'] or compare_versions(app['version'], held['version']) > 0):
            order[index] = app
    return [{key: app[key] for key in ('id','name','default','icon')} for app in order]


async def desktop_target(path, signal, internals):
    signal.throwIfAborted()
    target, _, run, options = facts(internals)
    if target == 'linux' and native_file_manager(options) == 'explorer':
        return 'win32', await translate(path, signal, run)
    return target, path


async def query_file_applications(path, signal, internals, display):
    signal.throwIfAborted()
    target, desktop_path = await desktop_target(path, signal, internals)
    _, env, run, _ = facts(internals)
    if target == 'linux':
        return await linux_file_applications(path, signal, run, env)
    if target == 'darwin':
        result = await run('osascript', ['-l', 'JavaScript', '-e', (RESOURCES/'file_applications.jxa').read_text(encoding='utf-8'), desktop_path, 'icons' if display else 'handlers'], signal)
        applications = parse_mac_applications(json.loads(result['stdout']))
        return dedupe_mac_applications(applications) if display else applications
    if target != 'win32':
        return []
    return parse_native_file_applications(json.loads(await windows_file_applications(desktop_path, None, signal, run)))


async def native_file_applications(path, signal, internals=None):
    return await query_file_applications(path, signal, internals, True)


async def open_native_file_application(path, application, signal, internals=None):
    target, desktop_path = await desktop_target(path, signal, internals)
    _, _, run, _ = facts(internals)
    if target == 'win32':
        await windows_file_applications(desktop_path, application, signal, run)
        return
    applications = await query_file_applications(path, signal, internals, False)
    if not any(app['id'] == application for app in applications):
        raise RuntimeError('Application is not registered for this file')
    await run('gio' if target == 'linux' else 'open', ['launch', application, path] if target == 'linux' else ['-a', application, path], signal)
