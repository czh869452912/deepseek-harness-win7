"""
1:1 Test Parity for @deepseek-ai/dsh-util-workspace-path
Matching reference/packages/util/workspace-path/tests/index.spec.ts
"""

from dsh.workspace.paths import (
    abbreviate_home_path,
    resolve_workspace_path,
    workspace_title_of,
    is_windows_style_path,
)


def test_resolve_workspace_path():
    """Verify resolving relative paths without changing absolute paths."""
    assert resolve_workspace_path("/w", "src/a.ts") == "/w/src/a.ts"
    assert resolve_workspace_path("/w/", "/abs/a.ts") == "/abs/a.ts"
    assert resolve_workspace_path(None, "src/a.ts") == "src/a.ts"
    assert resolve_workspace_path("", "src/a.ts") == "src/a.ts"
    assert resolve_workspace_path("/w", "C:\\x\\a.ts") == "C:\\x\\a.ts"
    assert resolve_workspace_path("/w", "\\\\server\\share") == "\\\\server\\share"


def test_abbreviate_home_path():
    """Verify abbreviating only descendants of a POSIX home."""
    assert abbreviate_home_path("/Users/u", "/Users/u") == "~"
    assert abbreviate_home_path("/Users/u/", "/Users/u") == "~"
    assert abbreviate_home_path("/Users/u/Documents/project", "/Users/u") == "~/Documents/project"
    assert abbreviate_home_path("/Users/u2/a.ts", "/Users/u") == "/Users/u2/a.ts"
    assert abbreviate_home_path("/Users/u/a.ts") == "/Users/u/a.ts"
    assert abbreviate_home_path("/Users/u/a.ts", "") == "/Users/u/a.ts"
    assert abbreviate_home_path("/etc/hosts", "/") == "/etc/hosts"
    assert abbreviate_home_path("C:\\Users\\u\\project", "C:\\Users\\u") == "C:\\Users\\u\\project"
    assert abbreviate_home_path("\\\\server\\share\\u", "\\\\server\\share\\u") == "\\\\server\\share\\u"


def test_workspace_title_of():
    """Verify reading the final path segment on both path styles."""
    assert workspace_title_of("/work/project/") == "project"
    assert workspace_title_of("C:\\work\\project\\") == "project"
    assert workspace_title_of("/") == ""
