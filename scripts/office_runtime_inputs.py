"""Offline build-input selection and exact Office runtime copying."""
import json
import os
from pathlib import Path
import shutil

from dsh.office.runtime_inputs import MANIFESTS, verify_installed_runtime


def office_runtime_source(root, explicit=None, architecture='x64'):
    if architecture not in MANIFESTS:
        raise ValueError('Unsupported Office runtime architecture.')
    selected = explicit or os.environ.get('DSH_OFFICE_RUNTIME_INPUT_ROOT') or str(Path(root) / 'vendor/office-runtime')
    source = Path(selected).absolute() / architecture
    try:
        verify_installed_runtime(source, architecture)
    except (OSError, ValueError) as cause:
        raise ValueError('Pinned offline Office runtime input is missing or changed: ' + str(source)) from cause
    return source


def bundle_office_runtime(destination, source, architecture='x64'):
    """Copy only the approved inventory to a new owned distribution directory."""
    source = Path(source).absolute()
    verify_installed_runtime(source, architecture)
    manifest = json.loads((source / 'runtime.json').read_text(encoding='utf-8'))
    destination = Path(destination).absolute() / 'dsh/office/bin' / architecture
    destination.mkdir(parents=True, exist_ok=False)
    succeeded = False
    try:
        for name in list(manifest['resources']) + ['runtime.json']:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(source / name), str(target))
        verify_installed_runtime(destination, architecture)
        succeeded = True
    finally:
        if not succeeded:
            shutil.rmtree(str(destination))
    return manifest
