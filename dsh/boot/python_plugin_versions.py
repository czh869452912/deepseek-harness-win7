"""Stopped-profile Python package replacement with retained source generations."""
import copy
import json
import os
import shutil
import uuid

from dsh.boot import python_plugins as store
from dsh.boot.profile import package_dir_from_anchor, read_profile_manifest
from dsh.boot.profile_lease import ProfileLease
from dsh.boot.python_package import inside, package_name

HISTORY = '.dsh-python-history'


def generation(record):
    payload = dict(version=record['version'], files=record['files'])
    return store.digest(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode('utf-8'))


def owned_path(directory, relative):
    """Reject links on every profile-owned ancestor before touching snapshots."""
    root = os.path.abspath(directory)
    path = inside(root, relative)
    current = root
    for part in os.path.relpath(path, root).split(os.sep):
        current = os.path.join(current, part)
        if os.path.lexists(current) and store.reparse(current):
            raise ValueError('plugin snapshot path must not be a link or junction')
    return path


def archive_path(directory, name, record):
    expected = generation(record)
    if record.get('generation', expected) != expected:
        raise ValueError('plugin history generation differs from its content record')
    return owned_path(directory, HISTORY + '/' + package_name(name) + '/' + expected)


def verify(path, files):
    if not os.path.isdir(path) or store.file_hashes(path) != files:
        raise RuntimeError('plugin transaction files changed or are missing; recovery requires inspection')


def managed(directory, name, manifest):
    package_name(name)
    record = manifest.get('dsh', {}).get('pythonPlugins', {}).get(name)
    if record is None:
        raise ValueError('package is not managed by the Python installer')
    target = store.destination(directory, name)
    if store.file_hashes(target) != record['files']:
        raise ValueError('installed plugin files changed; preserve or restore them before replacing')
    descriptor = store.validate_package(target)
    if descriptor['name'] != name or descriptor['version'] != record['version']:
        raise ValueError('installed plugin identity differs from its profile record')
    if manifest.get('dependencies', {}).get(name) != 'file:node_modules/' + name or name not in manifest.get('dsh', {}).get('profile', {}).get('bundles', []):
        raise ValueError('managed Python plugin profile references changed')
    return target, record


def stage_source(directory, source):
    token = uuid.uuid4().hex
    stage = owned_path(directory, store.STAGING + '/' + token)
    os.makedirs(stage)
    try:
        copied = store.copy_source(os.path.abspath(source), stage)
        if copied != stage:
            flat = owned_path(directory, store.STAGING + '/' + uuid.uuid4().hex)
            os.replace(copied, flat)
            shutil.rmtree(stage)
            os.replace(flat, stage)
        return token, stage
    except BaseException:
        if os.path.isdir(stage):
            shutil.rmtree(stage)
        raise


def profile_bytes(directory):
    with open(os.path.join(directory, 'package.json'), 'rb') as stream:
        data = stream.read()
    return data, read_profile_manifest('dsh', directory)


def publish_replace(directory, before_bytes, after, name, token, old, new):
    profile = os.path.join(directory, 'package.json')
    target = store.destination(directory, name)
    stage = owned_path(directory, store.STAGING + '/' + token)
    backup = owned_path(directory, store.STAGING + '/' + token + '-old')
    archive = archive_path(directory, name, old)
    if os.path.exists(archive):
        verify(archive, old['files'])
    after_bytes = store.json_bytes(after)
    journal = dict(operation='replace', name=name, token=token, before=store.digest(before_bytes),
        after=store.digest(after_bytes), old=old, new=new)
    with open(profile, 'rb') as stream:
        if stream.read() != before_bytes:
            raise RuntimeError('profile changed while preparing plugin transaction')
    store.atomic_bytes(os.path.join(directory, store.JOURNAL), store.json_bytes(journal))
    try:
        with open(profile, 'rb') as stream:
            if stream.read() != before_bytes:
                raise RuntimeError('profile changed while preparing plugin transaction')
        verify(target, old['files'])
        verify(stage, new['files'])
        os.replace(target, backup)
        os.replace(stage, target)
        store.atomic_bytes(profile, after_bytes)
    finally:
        store.recover(directory)


def recover_replace(directory, transaction, committed):
    name, token = transaction['name'], transaction['token']
    target = store.destination(directory, name)
    stage = owned_path(directory, store.STAGING + '/' + token)
    backup = owned_path(directory, store.STAGING + '/' + token + '-old')
    old, new = transaction['old'], transaction['new']
    archive = archive_path(directory, name, old)
    # Validate every candidate before removing or moving anything. If files or
    # profile were edited outside the transaction, retain the journal for review.
    if os.path.exists(stage):
        verify(stage, new['files'])
    if os.path.exists(backup):
        verify(backup, old['files'])
    if os.path.exists(archive):
        verify(archive, old['files'])
    if committed:
        verify(target, new['files'])
        if not os.path.exists(backup) and not os.path.exists(archive):
            raise RuntimeError('committed replacement is missing its previous generation')
        if os.path.exists(backup):
            if os.path.exists(archive):
                shutil.rmtree(backup)
            else:
                os.makedirs(os.path.dirname(archive), exist_ok=True)
                os.replace(backup, archive)
    elif os.path.exists(backup):
        if os.path.exists(target):
            verify(target, new['files'])
            shutil.rmtree(target)
        os.replace(backup, target)
    else:
        verify(target, old['files'])
    if os.path.exists(stage):
        shutil.rmtree(stage)
    os.unlink(os.path.join(directory, store.JOURNAL))


def replace_candidate(directory, before_bytes, before, token, stage, expected_name=None, acquisition=None):
    from dsh.boot.app_boot import load_overlay_patches
    descriptor = store.validate_package(stage)
    name = descriptor['name']
    if expected_name is not None and name != expected_name:
        raise ValueError('rollback package identity differs from the installed plugin')
    target, record = managed(directory, name, before)
    load_overlay_patches('dsh', inside(stage, descriptor['dsh']['bundle']['patch']))
    new = dict(version=descriptor['version'], files=store.file_hashes(stage))
    from dsh.boot.python_plugin_dependencies import profile_libraries
    profile_libraries(directory, stage, replacing=name)
    if acquisition is not None:
        new['acquisition'] = copy.deepcopy(acquisition)
    if new['version'] == record['version']:
        raise ValueError('replacement must have a different version; published versions are immutable')
    history = copy.deepcopy(record.get('history', []))
    for previous in history:
        verify(archive_path(directory, name, previous), previous['files'])
        if previous['version'] == new['version'] and previous['files'] != new['files']:
            raise ValueError('this version already has a different recorded source generation')
    old = dict(version=record['version'], files=record['files'])
    if 'acquisition' in record:
        old['acquisition'] = copy.deepcopy(record['acquisition'])
    old['generation'] = generation(old)
    history = [previous for previous in history if previous['generation'] not in (generation(new), old['generation'])]
    history.append(old)
    after = copy.deepcopy(before)
    after['dsh']['pythonPlugins'][name] = dict(new, history=history)
    publish_replace(directory, before_bytes, after, name, token, old, new)
    return name


def upgrade(directory, source, installation_anchor, acquisition=None):
    from dsh.boot.python_plugin_acquisition import verified_record
    with ProfileLease(directory, exclusive=True):
        store.recover(directory)
        acquisition = verified_record(source, acquisition)
        token, stage = stage_source(directory, source)
        try:
            descriptor = store.validate_package(stage)
            name = descriptor['name']
            if name.startswith('@deepseek-ai/') or package_dir_from_anchor(installation_anchor, name) is not None:
                raise ValueError('Python plugins cannot replace installation-owned package identities')
            before_bytes, before = profile_bytes(directory)
            return replace_candidate(directory, before_bytes, before, token, stage, acquisition=acquisition)
        finally:
            if os.path.isdir(stage) and not os.path.exists(os.path.join(directory, store.JOURNAL)):
                shutil.rmtree(stage)


def rollback(directory, name, version=None):
    with ProfileLease(directory, exclusive=True):
        store.recover(directory)
        before_bytes, before = profile_bytes(directory)
        _, record = managed(directory, name, before)
        history = record.get('history', [])
        choices = [previous for previous in history if version is None or previous['version'] == version]
        if not choices:
            raise ValueError('no retained plugin version is available for rollback')
        selected = choices[-1]
        source = archive_path(directory, name, selected)
        verify(source, selected['files'])
        token, stage = stage_source(directory, source)
        try:
            return replace_candidate(directory, before_bytes, before, token, stage, name, selected.get('acquisition'))
        finally:
            if os.path.isdir(stage) and not os.path.exists(os.path.join(directory, store.JOURNAL)):
                shutil.rmtree(stage)


def versions(directory, name):
    with ProfileLease(directory):
        if os.path.exists(os.path.join(directory, store.JOURNAL)):
            raise RuntimeError('pending plugin transaction; recover it before listing versions')
        before = read_profile_manifest('dsh', directory)
        _, record = managed(directory, name, before)
        result = [dict(version=record['version'], generation=generation(record), current=True)]
        if 'acquisition' in record:
            result[0]['acquisition'] = copy.deepcopy(record['acquisition'])
        for previous in record.get('history', []):
            verify(archive_path(directory, name, previous), previous['files'])
            result.append(dict(version=previous['version'], generation=generation(previous), current=False))
            if 'acquisition' in previous:
                result[-1]['acquisition'] = copy.deepcopy(previous['acquisition'])
        return dict(name=name, versions=result)
