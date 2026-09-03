"""
1:1 parity unit test suite for dsh/cordis/include.py matching reference/vendor/include/src/index.ts.
Covers:
- T1: init with missing file and initial config writes and applies; without initial raises FileNotFoundError
- T2: internal/update awaits update and short-circuits (does not call next)
- T4: write_file does not reorder keys
- T5: write to readonly config raises PermissionError
- T6: read classifies errors into stage 'read', 'parse', 'validate'
"""

import asyncio
import os
import stat
import tempfile
import pytest

from dsh.cordis.context import Context
from dsh.cordis.include import IncludeService, ConfigFileError


def test_t1_include_init_missing_file_with_initial_writes_and_applies():
    """T1: init with missing file writes initial config; missing file without initial raises."""
    ctx = Context()
    tmp_dir = tempfile.mkdtemp()
    missing_path = os.path.join(tmp_dir, "new_config.yaml")

    try:
        # 1. With initial
        inc = IncludeService(ctx, {
            "path": missing_path,
            "initial": [{"id": "sub1", "name": "plugin-a"}]
        })
        gen = inc.init()
        next(gen)  # Yields teardown

        assert os.path.exists(missing_path)
        assert inc.data == [{"id": "sub1", "name": "plugin-a"}]

        # 2. Without initial on another missing file
        missing_path2 = os.path.join(tmp_dir, "no_init.yaml")
        inc2 = IncludeService(ctx, {"path": missing_path2})
        with pytest.raises(ConfigFileError) as exc_info:
            gen2 = inc2.init()
            next(gen2)
        assert exc_info.value.stage == "read"
        assert "not found" in str(exc_info.value)
    finally:
        if os.path.exists(missing_path):
            os.remove(missing_path)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)


@pytest.mark.asyncio
async def test_t2_include_internal_update_short_circuits_and_awaits():
    """T2: internal/update matching path applies update and short-circuits next."""
    ctx = Context()
    tmp_file = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
    tmp_file.write(b"- id: item1\n  name: plugin-a\n  config:\n    key: initial\n")
    tmp_file.close()

    try:
        inc = IncludeService(ctx, {"path": tmp_file.name})
        gen = inc.init()
        next(gen)

        next_called = [False]

        def subsequent_listener():
            next_called[0] = True

        # Emit internal/update matching path
        update_data = {
            "path": tmp_file.name,
            "patches": [{"id": "item1", "name": "plugin-a", "config": {"key": "updated"}}]
        }

        # Dispatch internal/update waterfall
        await ctx.events.waterfall(
            "internal/update",
            update_data,
            False,
            next_fn=subsequent_listener,
            caller_ctx=ctx
        )

        assert next_called[0] is False
        assert inc.root.data[0]["config"]["key"] == "updated"
    finally:
        if os.path.exists(tmp_file.name):
            os.remove(tmp_file.name)


def test_t4_include_write_back_does_not_reorder_keys():
    """T4: Writing config back does not reorder dictionary keys."""
    ctx = Context()
    tmp_file = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
    tmp_file.close()

    try:
        inc = IncludeService(ctx, {"path": tmp_file.name})
        custom_entry = {"zebra": 1, "apple": 2, "middle": 3}
        inc._write_file_sync([custom_entry])

        with open(tmp_file.name, "r", encoding="utf-8") as f:
            content = f.read()

        # Keys should appear in the original insertion order (zebra before apple)
        zebra_idx = content.find("zebra")
        apple_idx = content.find("apple")
        assert zebra_idx != -1 and apple_idx != -1
        assert zebra_idx < apple_idx
    finally:
        if os.path.exists(tmp_file.name):
            os.remove(tmp_file.name)


def test_t5_include_readonly_write_raises():
    """T5: Writing to readonly config raises PermissionError."""
    ctx = Context()
    tmp_file = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
    tmp_file.write(b"- id: readonly_test\n")
    tmp_file.close()

    try:
        inc = IncludeService(ctx, {"path": tmp_file.name})
        gen = inc.init()
        next(gen)

        inc.readonly = True
        with pytest.raises(PermissionError) as exc_info:
            inc._write_file_sync([{"id": "new"}])
        assert "cannot overwrite readonly config" in str(exc_info.value)
    finally:
        if os.path.exists(tmp_file.name):
            os.remove(tmp_file.name)


@pytest.mark.asyncio
async def test_t6_include_read_stages_parse_and_validate_errors():
    """T6: read classifies bad YAML into 'parse' and non-array into 'validate'."""
    ctx = Context()

    # 1. Parse error
    tmp_parse = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
    tmp_parse.write(b": bad yaml syntax [[\n")
    tmp_parse.close()

    try:
        inc = IncludeService(ctx, {"path": tmp_parse.name})
        with pytest.raises(ConfigFileError) as exc:
            await inc.read()
        assert exc.value.stage == "parse"
    finally:
        if os.path.exists(tmp_parse.name):
            os.remove(tmp_parse.name)

    # 2. Validate error (top-level dict instead of array)
    tmp_val = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
    tmp_val.write(b"not_an_array: true\n")
    tmp_val.close()

    try:
        inc2 = IncludeService(ctx, {"path": tmp_val.name})
        with pytest.raises(ConfigFileError) as exc:
            await inc2.read()
        assert exc.value.stage == "validate"
    finally:
        if os.path.exists(tmp_val.name):
            os.remove(tmp_val.name)
