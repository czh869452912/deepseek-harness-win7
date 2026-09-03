"""
1:1 parity unit test suite for dsh/cordis/environment.py matching reference launch-environment & home-paths.
Covers:
- T1: resolve_dsh_home expands '~' properly
- T2: parse_dotenv handles inline comments, multiline quoted values, and single quote literals
- T3: parse_dotenv escape sequence handling (does not turn '\\n' into newline)
- T4: launch_environment_of returns process-only snapshot when not mounted
- T5: snapshot is immutable against subsequent os.environ or layer dict modifications
"""

import os
import sys
import tempfile
import pytest

from dsh.cordis.context import Context
from dsh.cordis.environment import (
    resolve_dsh_home,
    expand_home_path,
    parse_dotenv,
    launch_environment_of,
    LaunchEnvironmentSnapshot,
    LAUNCH_ENVIRONMENT_KEY,
)


def test_t1_resolve_dsh_home_expands_tilde():
    """T1: resolve_dsh_home expands '~' and '~/...' to user home, not cwd."""
    home_dir = os.path.expanduser("~")

    # 1. '~' alone
    res1 = resolve_dsh_home(custom_home="~")
    assert res1 == os.path.abspath(home_dir)

    # 2. '~/my-dsh'
    res2 = resolve_dsh_home(custom_home="~/my-dsh")
    assert res2 == os.path.abspath(os.path.join(home_dir, "my-dsh"))

    # 3. Environment variable DSH_HOME="~/env-dsh"
    res3 = resolve_dsh_home(env={"DSH_HOME": "~/env-dsh"})
    assert res3 == os.path.abspath(os.path.join(home_dir, "env-dsh"))

    # 4. Blank DSH_HOME falls back to ~/.dsh
    res4 = resolve_dsh_home(env={"DSH_HOME": "   "})
    assert res4 == os.path.abspath(os.path.join(home_dir, ".dsh"))


def test_t2_parse_dotenv_inline_comment_and_multiline():
    """T2: parse_dotenv strips inline comments from unquoted values, handles multiline values."""
    content = """
# Header comment
KEY1=val1 # inline comment
KEY2="quoted # not a comment"
KEY3='single # literal'
MULTILINE="line 1
line 2"
SINGLE_MULTI='part 1
part 2'
"""
    res = parse_dotenv(content)
    assert res["KEY1"] == "val1"
    assert res["KEY2"] == "quoted # not a comment"
    assert res["KEY3"] == "single # literal"
    assert res["MULTILINE"] == "line 1\nline 2"
    assert res["SINGLE_MULTI"] == "part 1\npart 2"


def test_t3_parse_dotenv_escape_order():
    """T3: parse_dotenv handles escapes without expanding double backslash before n."""
    content = r"""
ESCAPE1="hello\nworld"
ESCAPE2="path\\nfile"
ESCAPE3="quote\"inside"
"""
    res = parse_dotenv(content)
    assert res["ESCAPE1"] == "hello\nworld"
    assert res["ESCAPE2"] == "path\\nfile"
    assert res["ESCAPE3"] == 'quote"inside'


def test_t4_launch_environment_of_falls_back_to_process():
    """T4: launch_environment_of returns process-only snapshot when context lacks service."""
    ctx = Context()
    snap = launch_environment_of(ctx)
    assert isinstance(snap, LaunchEnvironmentSnapshot)
    entry = snap.get("PATH")
    assert entry is not None
    assert entry.source == "process"

    # When mounted, returns the registered instance
    custom_snap = LaunchEnvironmentSnapshot([{"source": "project-env", "values": {"FOO": "bar"}}])
    ctx.set_service(LAUNCH_ENVIRONMENT_KEY, custom_snap)
    assert launch_environment_of(ctx) is custom_snap


def test_t5_snapshot_is_immutable_after_load():
    """T5: Mutating the source dictionary does not alter the constructed snapshot."""
    vals = {"TEST_VAR": "original"}
    layer = {"source": "project-env", "values": vals}
    snap = LaunchEnvironmentSnapshot([layer])

    # Mutate original dictionary
    vals["TEST_VAR"] = "mutated"

    assert snap.get_value("TEST_VAR") == "original"
