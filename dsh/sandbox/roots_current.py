"""Current physical writable-root derivation shared by enforcing providers."""
import os
import tempfile

from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import js_to_string
from dsh.jobs.pump import field
from .policy_current import SandboxInvalidRootError
from .roots import canonical_path


def additional_root(path):
    try:
        # Existing ancestors must resolve on this host; a missing explicit
        # grant is an error, unlike the conservative workspace fallback.
        os.stat(path)
        physical=os.path.realpath(path)
        directory=os.path.isdir(physical)
    except (OSError,ValueError) as error:
        raise SandboxInvalidRootError(path,'cannot read the directory: '+js_to_string(error)) from error
    if not directory:raise SandboxInvalidRootError(path,'expected an existing directory')
    try:same=os.path.relpath(path,physical)=='.'
    except ValueError:same=False
    if not same:raise SandboxInvalidRootError(path,'use the physical directory path '+stringify_json(physical)+'; symlinked grants are not supported')
    return physical


def workspace_writable_roots(policy):
    if field(policy,'mode')!='workspace-write':return []
    additional=[additional_root(path) for path in field(policy,'additionalWritableRoots',[]) or []]
    return list(dict.fromkeys([canonical_path(field(policy,'workspaceRoot'))]+additional))


def writable_roots(policy):
    if field(policy,'mode')!='workspace-write':return []
    return list(dict.fromkeys(workspace_writable_roots(policy)+[canonical_path('/tmp'),canonical_path(tempfile.gettempdir())]))
