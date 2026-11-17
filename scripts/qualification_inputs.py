"""Freeze the actual prepared dependencies consumed by a qualification run.

Lockfiles describe intended inputs. These identities also bind installed code,
resolved directory links and the Python files the Portable builder copies.
"""
import hashlib
import os
from pathlib import Path
import stat


VOLATILE_DIRECTORIES = frozenset(('.git', '.vite', '.vite-temp', '.cache', '__pycache__'))


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def tree_identity(roots, approved, progress=None):
    """Read a bounded graph of real directories, following each target once.

    Reparse targets must stay within the explicitly approved input roots. Link
    identities are retained even when their contents were visited already.
    No attributes, ACLs or input files are changed.
    """
    approved = tuple(Path(path).resolve(strict=True) for path in approved)
    files, links, missing_links, visited = {}, {}, {}, set()

    def bounded(path, strict=True):
        target = path.resolve(strict=strict)
        if not any(target == root or root in target.parents for root in approved):
            raise ValueError('Qualification input link escaped approved roots: ' + str(path))
        return target

    def visit(path):
        info = path.lstat()
        linked = stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
        # Every ordinary child already has a resolved, approved parent. Resolving
        # each file again performs a Windows reparse query for every ancestor;
        # only roots and actual links need that work.
        try:
            target = bounded(path) if linked else path
        except FileNotFoundError:
            if not linked:
                raise
            # pnpm may retain links for an unavailable optional dependency.
            # Bind that absence, too: adding its target during the gate changes
            # this manifest. Actual consumers still fail if they require it.
            raw = Path(os.readlink(str(path)))
            target = bounded(raw if raw.is_absolute() else path.parent / raw, strict=False)
            missing_links[str(path.absolute())] = str(target)
            return
        if linked:
            links[str(path.absolute())] = str(target)
        if target in visited:
            return
        visited.add(target)
        if target.is_dir():
            with os.scandir(str(target)) as entries:
                children = sorted(entries, key=lambda entry: entry.name)
            for child in children:
                if child.name in VOLATILE_DIRECTORIES or child.name.endswith(('.pyc', '.pyo')):
                    continue
                visit(Path(child.path))
        elif target.is_file():
            files[str(target)] = digest(target)
            if progress is not None and len(files) % 2000 == 0:
                progress(dict(path=str(target), files=len(files), links=len(links)))
        else:
            raise ValueError('Unsupported qualification input: ' + str(path))

    for root in roots:
        path = Path(root).absolute()
        target = bounded(path)
        if target != path:
            links[str(path)] = str(target)
        visit(target)
    return dict(files=dict(sorted(files.items())), links=dict(sorted(links.items())),
                missing_links=dict(sorted(missing_links.items())),
                excluded_directories=sorted(VOLATILE_DIRECTORIES), excluded_suffixes=['.pyc', '.pyo'])


def python_identity(root, runtime, site_packages, architecture):
    """Use the builder's exact runtime/dependency selection, including bytes."""
    from scripts.build_portable import checked_inputs, inspect_runtime
    root, runtime, site_packages = [Path(path).resolve(strict=True)
                                    for path in (root, runtime, site_packages)]
    observed = inspect_runtime(str(runtime), architecture)
    _, distributions = checked_inputs(root, site_packages, architecture)
    files = {}

    def add(path):
        path = path.resolve(strict=True)
        if not any(path == base or base in path.parents for base in (runtime, site_packages)):
            raise ValueError('Python build input escaped approved runtime/dependencies')
        files[str(path)] = digest(path)

    for path in runtime.iterdir():
        if path.name.lower().endswith(('.dll', '.exe')) or path.name == 'LICENSE.txt':
            add(path)
    # Match bundle_python_runtime's exclusions; DLLs have no exclusions there.
    for name in ('Lib', 'DLLs'):
        folder = runtime / name
        if not folder.exists():
            continue
        for directory, children, names in os.walk(str(folder), followlinks=False):
            if name == 'Lib':
                children[:] = [item for item in children if item not in
                               ('site-packages', '__pycache__', 'test', 'tests')]
            for child in children:
                info = (Path(directory) / child).lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Linked Python runtime directory is not an approved copy input')
            for filename in names:
                add(Path(directory) / filename)
    selected = []
    for distribution in distributions:
        selected.append(dict(name=distribution.metadata['Name'], version=distribution.version))
        for relative in distribution.files:
            if relative.suffix != '.pyc' and '..' not in relative.parts:
                add(Path(distribution.locate_file(relative)))
    return dict(runtime=str(runtime), site_packages=str(site_packages), observed=observed,
                distributions=sorted(selected, key=lambda item: item['name']), files=dict(sorted(files.items())))
