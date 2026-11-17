"""Read exported plugin display resources without importing plugin code."""
import base64
import errno
import json
import ntpath
import os
from pathlib import Path
import re
import stat
from dsh.boot.package_resolution import resolve_plugin_resource, resolution_read_scope
from dsh.boot.plugin_packages import bare_package_name

_MISSING = object()
_LANGUAGE = re.compile(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*\Z')
MAX_ICON_BYTES = 256 * 1024
_MEDIA = {'.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
          '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
_WHITESPACE = '\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def _optional(specifier, parent_url, packages):
    try:
        return resolve_plugin_resource(specifier, parent_url, packages)
    except (ImportError, OSError) as error:
        if getattr(error, 'code', None) in ('ERR_PACKAGE_PATH_NOT_EXPORTED', 'ERR_MODULE_NOT_FOUND', 'MODULE_NOT_FOUND', 'ENOENT', 'ENOTDIR') or getattr(error, 'errno', None) in (errno.ENOENT, errno.ENOTDIR):
            return None
        raise


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(label+' must be an object')
    return value


def _text(value, label):
    if value is _MISSING:
        return None
    if not isinstance(value, str) or not value.strip(_WHITESPACE):
        raise ValueError(label+' must be a non-empty string')
    return value


def _read_object(filename):
    def invalid_constant(value):
        raise ValueError('Invalid JSON constant '+value)
    try:
        with open(filename, 'r', encoding='utf-8', errors='replace') as stream:
            value = json.load(stream, parse_constant=invalid_constant)
    except (ValueError, OSError) as error:
        raise ValueError(filename+': '+str(error)) from error
    return _object(value, filename)


def _fallback(value):
    return value if isinstance(value, str) and value.strip(_WHITESPACE) else None


def _dictionaries(english, specifier, parent_url, packages):
    dictionaries = {}
    for entry in sorted(os.listdir(os.path.dirname(english))):
        if not entry.endswith('.json'):
            continue
        resource = specifier+'/locale/'+entry
        language = entry[:-5]
        if not _LANGUAGE.fullmatch(language):
            raise ValueError(resource+' must use a language id as its filename')
        language = language.lower()
        if language in dictionaries:
            raise ValueError(resource+' duplicates locale '+language)
        filename = resolve_plugin_resource(resource, parent_url, packages)
        if os.path.dirname(filename) != os.path.dirname(english):
            raise ValueError(resource+': '+filename+' must share the English locale directory '+os.path.dirname(english))
        parsed = _read_object(filename)
        meta = {} if 'meta' not in parsed else _object(parsed['meta'], filename+': meta')
        dictionaries[language] = {key: _text(meta.get(key, _MISSING), filename+': meta.'+key) for key in ('title', 'description')}
    return dictionaries


def _localized(field, dictionaries, fallback, final):
    entries = {language: fields[field] for language, fields in dictionaries.items() if fields[field] is not None}
    if not entries:
        return fallback
    result = {'en': final if fallback is None else fallback}
    result.update(entries)
    return result


def _package_owned(filename, name):
    directory = os.path.dirname(filename)
    while True:
        manifest = os.path.join(directory, 'package.json')
        if os.path.exists(manifest) and _read_object(manifest).get('name') == name:
            return
        parent = os.path.dirname(directory)
        if parent == directory:
            raise ValueError(filename+': icon must remain inside its package directory')
        directory = parent


def _icon(specifier, package_name, parent_url, manifest_path, value, packages):
    icon = None if manifest_path is None else _text(value, manifest_path+': icon')
    if icon is not None:
        if os.path.isabs(icon) or ntpath.isabs(icon) or re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', icon):
            raise ValueError(manifest_path+': icon must be a relative file path')
        label = manifest_path
        root = str(Path(os.path.dirname(manifest_path)).resolve(strict=True))
        target = os.path.abspath(os.path.join(root, icon))
        real = str(Path(target).resolve(strict=True))
        try:
            confined = os.path.normcase(os.path.commonpath([root, real])) == os.path.normcase(root)
        except ValueError:
            confined = False
        if not confined:
            raise ValueError(label+': icon must remain inside its manifest directory')
    else:
        target = _optional(specifier+'/icon', parent_url, packages)
        if target is None:
            return None
        label = target
        real = str(Path(target).resolve(strict=True))
        _package_owned(real, package_name)
    media_type = _MEDIA.get(os.path.splitext(target)[1].lower())
    if media_type is None:
        raise ValueError(label+': icon must be SVG, PNG, JPEG, or WebP')
    information = os.stat(real)
    if not stat.S_ISREG(information.st_mode):
        raise ValueError(label+': icon must be a regular file')
    if information.st_size > MAX_ICON_BYTES:
        raise ValueError(label+': icon exceeds 256 KiB')
    with open(real, 'rb') as stream:
        data = stream.read(MAX_ICON_BYTES+1)
    if len(data) > MAX_ICON_BYTES:
        raise ValueError(label+': icon exceeds 256 KiB')
    return 'data:'+media_type+';base64,'+base64.b64encode(data).decode('ascii')


def read_plugin_meta(specifier, parent_url, packages=None):
    with resolution_read_scope():
        return _read_plugin_meta(specifier, parent_url, packages)


def _read_plugin_meta(specifier, parent_url, packages=None):
    package_name = bare_package_name(specifier)
    if package_name is None:
        return None
    def diagnostic(error):
        return 'Plugin metadata for '+specifier+': Error: '+str(error)
    try:
        english = _optional(specifier+'/locale/en.json', parent_url, packages)
        dictionaries = {} if english is None else _dictionaries(english, specifier, parent_url, packages)
        manifest_path = _optional(specifier+'/package.json', parent_url, packages) if package_name == specifier else None
        manifest = {} if manifest_path is None else _read_object(manifest_path)
        result = {}
        for field, fallback, final in [('title', _fallback(manifest.get('name')), specifier),
                                       ('description', _fallback(manifest.get('description')), '')]:
            text = _localized(field, dictionaries, fallback, final)
            if text is not None:
                result[field] = text
        try:
            icon = _icon(specifier, package_name, parent_url, manifest_path, manifest.get('icon', _MISSING), packages)
        except Exception as error:
            result['error'] = diagnostic(error)
            return result
        if icon is not None:
            result['icon'] = icon
        return result or None
    except Exception as error:
        return {'error': diagnostic(error)}


readPluginMeta = read_plugin_meta
