import os
from pathlib import PurePosixPath


def resolve_import_path(root, name, missing_prefixes=None):
    selected = root / name
    if missing_prefixes is None or '..' in PurePosixPath(name).parts or PurePosixPath(name).as_posix() != name:
        return selected.resolve()
    prefix = name.split('/')[0]
    if prefix not in missing_prefixes:
        base = root / prefix
        missing_prefixes[prefix] = not os.path.lexists(str(base)) and base.resolve() == base
    return selected if missing_prefixes[prefix] else selected.resolve()
