"""Profile-owned local Python package installation with a recoverable commit point."""

import copy
import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
import zipfile

from dsh.boot.profile import package_dir_from_anchor, read_profile_manifest
from dsh.boot.profile_lease import ProfileLease
from dsh.boot.python_package import inside, package_name, relative_parts, validate_sources

MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 4096
JOURNAL = ".dsh-python-transaction.json"
STAGING = ".dsh-python-staging"


def atomic_bytes(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=".dsh-write-", dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reparse(path):
    return os.path.islink(path) or bool(getattr(os.lstat(path), "st_reparse_tag", 0))


def regular_tree(directory, ignore_git=False):
    seen, total, count = set(), 0, 0
    if reparse(directory):
        raise ValueError("plugin directory must not be a link or junction")
    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(name for name in dirs if not (ignore_git and name == ".git"))
        for name in dirs + sorted(files):
            path = os.path.join(root, name)
            relative = os.path.relpath(path, directory).replace("\\", "/")
            relative_parts(relative)
            key = relative.casefold()
            if key in seen or reparse(path):
                raise ValueError("duplicate path or linked plugin file: " + relative)
            seen.add(key)
            if os.path.isdir(path):
                continue
            if not stat.S_ISREG(os.stat(path).st_mode):
                raise ValueError("plugin files must be regular files")
            if "__pycache__" in relative.split("/") and name.endswith(".pyc"):
                continue
            count += 1
            total += os.path.getsize(path)
            if count > MAX_FILES or total > MAX_BYTES:
                raise ValueError("plugin exceeds installation size limits")
            if name.lower().endswith((".dll", ".pyd", ".so", ".exe", ".whl")):
                raise ValueError("native dependencies are not supported by this installer")
            yield relative, path


def copy_source(source, target):
    if os.path.isdir(source):
        try:
            source_contains_target = os.path.normcase(os.path.commonpath([os.path.realpath(source), os.path.realpath(target)])) == os.path.normcase(os.path.realpath(source))
        except ValueError:
            source_contains_target = False
        if source_contains_target:
            raise ValueError("installation staging must not be inside the source directory")
        descriptor_path = os.path.join(source, 'package.json')
        descriptor = None
        if os.path.isfile(descriptor_path):
            with open(descriptor_path, encoding='utf-8') as stream:
                descriptor = json.load(stream)
        if (isinstance(descriptor, dict) and isinstance(descriptor.get('dsh'), dict) and
                any(key in descriptor['dsh'] for key in ('sourceExport', 'release'))):
            from dsh.boot.python_plugin_export import release_files
            _, entries = release_files(source)
        else:
            entries = regular_tree(source, ignore_git=True)
        for relative, path in entries:
            destination = inside(target, relative)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copyfile(path, destination)
        return target
    if not zipfile.is_zipfile(source):
        raise ValueError("Python plugin source must be a directory or ZIP")
    with zipfile.ZipFile(source) as archive:
        seen, total = set(), 0
        entries = archive.infolist()
        if len(entries) > MAX_FILES:
            raise ValueError("plugin ZIP has too many entries")
        validated = []
        for entry in entries:
            if entry.orig_filename != entry.filename:
                raise ValueError("ZIP entry path was normalized; use relative POSIX paths")
            relative = entry.filename.rstrip("/") if entry.is_dir() else entry.filename
            relative_parts(relative)
            key = relative.casefold()
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if (key in seen or entry.flag_bits & 1 or mode not in (0, stat.S_IFREG, stat.S_IFDIR) or
                    (mode == stat.S_IFDIR and not entry.is_dir())):
                raise ValueError("duplicate, encrypted or nonregular ZIP entry")
            seen.add(key)
            total += entry.file_size
            if total > MAX_BYTES:
                raise ValueError("plugin ZIP exceeds installation size limit")
            validated.append((entry, relative))
        wrapped = not any(not entry.is_dir() and relative.casefold() == "package.json"
                          for entry, relative in validated)
        if wrapped:
            roots = {relative.split("/")[0].casefold() for _, relative in validated}
            if len(roots) != 1 or any(not entry.is_dir() and "/" not in relative
                                      for entry, relative in validated):
                raise ValueError("ZIP must contain one package root")
        for entry, relative in validated:
            if wrapped:
                relative = relative.partition("/")[2]
                if not relative:
                    continue
            destination = inside(target, relative)
            if entry.is_dir():
                os.makedirs(destination, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with archive.open(entry) as incoming, open(destination, "xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
    return target


def validate_package(directory):
    manifest = validate_sources(directory)
    if any(key in manifest.get('dsh', {}) for key in ('sourceExport', 'release')):
        from dsh.boot.python_plugin_export import release_files
        _, entries = release_files(directory)
        expected = {relative for relative, _ in entries}
        actual = {relative for relative, _ in regular_tree(directory)}
        if actual != expected:
            raise ValueError('exported package contains files outside its explicit release list')
    return manifest


def file_hashes(directory):
    result = {}
    for relative, path in regular_tree(directory):
        with open(path, "rb") as stream:
            result[relative] = digest(stream.read())
    return result


def destination(directory, name):
    modules = os.path.join(directory, "node_modules")
    os.makedirs(modules, exist_ok=True)
    if reparse(modules):
        raise ValueError("profile node_modules must not be a link or junction")
    path = inside(modules, package_name(name))
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    if reparse(parent) or (os.path.lexists(path) and reparse(path)):
        raise ValueError("plugin installation path must not be a link or junction")
    return path


def recover(directory):
    journal_path = os.path.join(directory, JOURNAL)
    if not os.path.isfile(journal_path):
        return
    with open(journal_path, encoding="utf-8") as stream:
        transaction = json.load(stream)
    token = transaction["token"]
    if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("invalid plugin recovery token")
    target = destination(directory, transaction["name"])
    stage = inside(directory, STAGING + "/" + token)
    if os.path.exists(stage) and reparse(stage):
        raise ValueError("plugin staging path is a link")
    with open(os.path.join(directory, "package.json"), "rb") as stream:
        current = digest(stream.read())
    if current not in (transaction["before"], transaction["after"]):
        raise RuntimeError("profile changed outside pending plugin transaction; recovery requires inspection")
    committed = current == transaction["after"]
    if transaction["operation"] == "replace":
        from dsh.boot.python_plugin_versions import recover_replace
        recover_replace(directory, transaction, committed)
        return
    for candidate in (target, stage):
        if os.path.isdir(candidate) and file_hashes(candidate) != transaction["files"]:
            raise RuntimeError("plugin transaction files changed; recovery requires inspection")
    if transaction["operation"] == "add":
        if committed and not os.path.isdir(target):
            raise RuntimeError("committed plugin package is missing")
        if not committed and os.path.exists(target):
            shutil.rmtree(target)
    elif transaction["operation"] == "remove":
        if committed and os.path.exists(target):
            raise RuntimeError("removed plugin package unexpectedly exists")
        if not committed and os.path.exists(stage):
            if os.path.exists(target):
                raise RuntimeError("both package and rollback copy exist")
            os.replace(stage, target)
    else:
        raise ValueError("invalid plugin recovery operation")
    if os.path.exists(stage):
        if reparse(stage):
            raise ValueError("plugin staging path is a link")
        shutil.rmtree(stage)
    os.unlink(journal_path)


def transact(directory, before, after, name, token, operation):
    profile_path = os.path.join(directory, "package.json")
    after_bytes = json_bytes(after)
    target = destination(directory, name)
    stage = inside(directory, STAGING + "/" + token)
    transaction = {"name": name, "token": token, "operation": operation,
                   "before": digest(before), "after": digest(after_bytes),
                   "files": file_hashes(stage if operation == "add" else target)}
    with open(profile_path, "rb") as stream:
        if stream.read() != before:
            raise RuntimeError("profile changed while preparing plugin transaction")
    atomic_bytes(os.path.join(directory, JOURNAL), json_bytes(transaction))
    try:
        with open(profile_path, "rb") as stream:
            if stream.read() != before:
                raise RuntimeError("profile changed while preparing plugin transaction")
        if operation == "add":
            os.replace(stage, target)
        else:
            os.replace(target, stage)
        atomic_bytes(profile_path, after_bytes)
    finally:
        recover(directory)


def install(directory, source, installation_anchor, acquisition=None):
    from dsh.boot.app_boot import load_overlay_patches
    from dsh.boot.python_plugin_acquisition import verified_record

    with ProfileLease(directory, exclusive=True):
        recover(directory)
        acquisition = verified_record(source, acquisition)
        staging = os.path.join(directory, STAGING)
        os.makedirs(staging, exist_ok=True)
        if reparse(staging):
            raise ValueError("plugin staging directory must not be a link")
        token = uuid.uuid4().hex
        stage = os.path.join(staging, token)
        os.makedirs(stage)
        try:
            copy_source(os.path.abspath(source), stage)
            manifest = validate_package(stage)
            name = manifest["name"]
            if name.startswith("@deepseek-ai/") or package_dir_from_anchor(installation_anchor, name) is not None:
                raise ValueError("Python plugins cannot replace installation-owned package identities")
            target = destination(directory, name)
            with open(os.path.join(directory, "package.json"), "rb") as stream:
                before_bytes = stream.read()
            before = read_profile_manifest("dsh", directory)
            if (os.path.lexists(target) or name in before.get("dependencies", {}) or
                    name in before.get("dsh", {}).get("profile", {}).get("bundles", [])):
                raise ValueError("package already exists; use upgrade for a managed Python plugin")
            patch = inside(stage, manifest["dsh"]["bundle"]["patch"])
            load_overlay_patches("dsh", patch)
            from dsh.boot.python_plugin_dependencies import profile_libraries
            profile_libraries(directory, stage)
            hashes = file_hashes(stage)
            after = copy.deepcopy(before)
            after.setdefault("dependencies", {})[name] = "file:node_modules/" + name
            dsh = after.setdefault("dsh", {})
            dsh.setdefault("profile", {}).setdefault("bundles", []).append(name)
            dsh.setdefault("pythonPlugins", {})[name] = {"version": manifest["version"], "files": hashes}
            if acquisition is not None:
                dsh['pythonPlugins'][name]['acquisition'] = acquisition
            transact(directory, before_bytes, after, name, token, "add")
            return name
        finally:
            if os.path.exists(stage) and not os.path.exists(os.path.join(directory, JOURNAL)):
                shutil.rmtree(stage)


def uninstall(directory, name):
    package_name(name)
    with ProfileLease(directory, exclusive=True):
        recover(directory)
        with open(os.path.join(directory, "package.json"), "rb") as stream:
            before_bytes = stream.read()
        before = read_profile_manifest("dsh", directory)
        records = before.get("dsh", {}).get("pythonPlugins", {})
        if name not in records:
            raise ValueError("package is not managed by the Python installer")
        target = destination(directory, name)
        if file_hashes(target) != records[name]["files"]:
            raise ValueError("installed plugin files changed; preserve or restore them before uninstalling")
        after = copy.deepcopy(before)
        after["dependencies"].pop(name, None)
        after["dsh"]["profile"]["bundles"] = [item for item in after["dsh"]["profile"]["bundles"] if item != name]
        after["dsh"]["pythonPlugins"].pop(name)
        staging = os.path.join(directory, STAGING)
        os.makedirs(staging, exist_ok=True)
        if reparse(staging):
            raise ValueError("plugin staging directory must not be a link")
        transact(directory, before_bytes, after, name, uuid.uuid4().hex, "remove")
