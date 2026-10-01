"""Python package descriptors and imports without changing global sys.path."""

import ast
import hashlib
import importlib
import importlib.machinery
import json
import os
import re
import sys
import types

from dsh import __version__

API_VERSION = 1
NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z")
RESERVED = {"con", "prn", "aux", "nul"} | {"com" + str(i) for i in range(1, 10)} | {"lpt" + str(i) for i in range(1, 10)}


def relative_parts(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("package paths must be nonempty relative POSIX paths")
    parts = value.split("/")
    for part in parts:
        if (not part or part in (".", "..") or part[-1] in " ." or
                any(c in part for c in '<>:"|?*') or any(ord(c) < 32 for c in part) or
                part.split(".")[0].lower() in RESERVED):
            raise ValueError("invalid package path: " + value)
    return parts


def package_name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("invalid Python plugin package name")
    relative_parts(value)
    return value


def inside(root, relative):
    path = os.path.join(root, *relative_parts(relative))
    if os.path.commonpath([os.path.realpath(root), os.path.realpath(path)]) != os.path.realpath(root):
        raise ValueError("package path escapes its root: " + relative)
    return path


def version_tuple(value, label):
    if (not isinstance(value, list) or len(value) != 3 or
            any(type(part) is not int or part < 0 for part in value)):
        raise ValueError(label + " must be a three-integer version array")
    return tuple(value)


def read_descriptor(directory):
    with open(os.path.join(directory, "package.json"), encoding="utf-8") as stream:
        manifest = json.load(stream)
    if not isinstance(manifest, dict):
        raise ValueError("package.json must be an object")
    package_name(manifest.get("name"))
    if not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        raise ValueError("package version must be nonempty")
    dsh = manifest.get("dsh")
    descriptor = dsh.get("python") if isinstance(dsh, dict) else None
    fields = {"apiVersion", "sourceRoot", "entry", "minPythonVersion", "minHostVersion", "dependencies"}
    if not isinstance(descriptor, dict) or set(descriptor) != fields:
        raise ValueError("dsh.python must declare exactly: " + ", ".join(sorted(fields)))
    if type(descriptor["apiVersion"]) is not int or descriptor["apiVersion"] != API_VERSION:
        raise ValueError("unsupported Python plugin API version")
    if tuple(sys.version_info[:3]) < version_tuple(descriptor["minPythonVersion"], "minPythonVersion"):
        raise ValueError("Python version does not satisfy this plugin")
    host = tuple(int(part) for part in __version__.split("."))
    if host < version_tuple(descriptor["minHostVersion"], "minHostVersion"):
        raise ValueError("host version does not satisfy this plugin")
    if descriptor["dependencies"] != []:
        raise ValueError("Python dependency installation is not implemented; dependencies must be []")
    if any(manifest.get(key) for key in ("dependencies", "optionalDependencies", "peerDependencies")):
        raise ValueError("external package dependencies are not supported by this installer")
    source_export = dsh.get('sourceExport')
    release = dsh.get('release')
    if 'release' in dsh:
        if 'sourceExport' in dsh:
            raise ValueError('choose exactly one release descriptor: release or sourceExport')
        if (not isinstance(release, dict) or set(release) != {'formatVersion', 'files'} or
                type(release['formatVersion']) is not int or release['formatVersion'] != 1):
            raise ValueError('invalid dsh.release descriptor')
        if (not isinstance(release['files'], list) or not release['files'] or
                any(type(item) is not str for item in release['files'])):
            raise ValueError('dsh.release.files must be a nonempty array of relative paths')
        for item in release['files']:
            inside(directory, item)
    if 'sourceExport' in dsh:
        if not isinstance(source_export, dict) or set(source_export) != {'record', 'files'}:
            raise ValueError('invalid sourceExport descriptor')
        release = source_export['files']
        if not isinstance(release, list) or not release or any(type(item) is not str for item in release):
            raise ValueError('sourceExport.files must be a nonempty array of relative paths')
        for item in release:
            inside(directory, item)
        record_path = inside(directory, source_export['record'])
        with open(record_path, encoding='utf-8') as stream:
            record = json.load(stream)
        if not isinstance(record, dict) or record.get('formatVersion') != 1:
            raise ValueError('unsupported source export record')
        if record.get('requiresClientBuild') is not False:
            raise ValueError('exported Client source requires a build before pack/install')
        if 'client' in record.get('sourceSha256', {}) and (not dsh.get('client') or not dsh.get('webArtifacts')):
            raise ValueError('exported Client source requires a build receipt and Client declaration')
    source = inside(directory, descriptor["sourceRoot"])
    if not os.path.isdir(source):
        raise ValueError("Python sourceRoot is missing")
    entry = descriptor["entry"]
    if not isinstance(entry, str) or entry.count(":") != 1:
        raise ValueError("entry must be module.path:Export")
    module, export = entry.split(":")
    if not all(part.isidentifier() and not part.startswith("_") for part in module.split(".") + [export]):
        raise ValueError("invalid Python entry module or export")
    path = inside(source, module.replace(".", "/") + ".py")
    if not os.path.isfile(path):
        path = inside(source, module.replace(".", "/") + "/__init__.py")
    if not os.path.isfile(path):
        raise ValueError("Python entry module is missing")
    bundle = dsh.get("bundle")
    if not isinstance(bundle, dict) or not isinstance(bundle.get("patch"), str):
        raise ValueError("Python plugin must declare dsh.bundle.patch")
    patch = inside(directory, bundle["patch"])
    if not os.path.isfile(patch):
        raise ValueError("bundle patch is missing")
    from dsh.boot.python_web_artifacts import validate_web_artifacts
    validate_web_artifacts(directory, manifest)
    return manifest, source, module, export, path


def validate_sources(directory):
    manifest, source, module, export, entry = read_descriptor(directory)
    for root, dirs, files in os.walk(source):
        for filename in files:
            if filename.endswith(".py"):
                path = os.path.join(root, filename)
                with open(path, "rb") as stream:
                    try:
                        compile(stream.read(), path, "exec", ast.PyCF_ONLY_AST, dont_inherit=True)
                    except SyntaxError as error:
                        raise ValueError("invalid Python syntax in " + path + ": " + str(error)) from error
    return manifest


def import_package(directory):
    manifest, source, module_name, export, path = read_descriptor(directory)
    identity = hashlib.sha256(os.path.realpath(source).encode("utf-8"))
    identity.update(b"\0")
    identity.update(manifest["version"].encode("utf-8"))
    for root, dirs, files in os.walk(source):
        dirs.sort()
        for filename in sorted(files):
            if filename.endswith(".py"):
                filename = os.path.join(root, filename)
                with open(filename, "rb") as stream:
                    record = [os.path.relpath(filename, source).replace("\\", "/"), hashlib.sha256(stream.read()).hexdigest()]
                identity.update(json.dumps(record, ensure_ascii=True).encode("ascii"))
    namespace = "_dsh_python_" + identity.hexdigest()[:24]
    before = set(sys.modules)
    if namespace not in sys.modules:
        package = types.ModuleType(namespace)
        package.__path__ = [source]
        package.__package__ = namespace
        package.__spec__ = importlib.machinery.ModuleSpec(namespace, loader=None, is_package=True)
        sys.modules[namespace] = package
    try:
        module = importlib.import_module(namespace + "." + module_name)
        plugin = getattr(module, export)
        if not callable(plugin) and not callable(getattr(plugin, "apply", None)):
            raise TypeError("Python entry export is not a Cordis plugin")
        return plugin, module
    except BaseException:
        for name in set(sys.modules) - before:
            if name == namespace or name.startswith(namespace + "."):
                sys.modules.pop(name, None)
        raise
