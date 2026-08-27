import asyncio
import builtins
import errno
import os
import stat as stat_module

import pytest

from dsh.cordis.context import Context
from dsh.fs.fs_local import FsError, FsLocalPlugin, FsService
import dsh.fs.fs_local as fs_local_module


class Signal:
    def __init__(self, aborted=False):
        self.aborted = aborted


class CountingSignal:
    def __init__(self, abort_on_check):
        self.abort_on_check = abort_on_check
        self.checks = 0

    @property
    def aborted(self):
        self.checks += 1
        return self.checks >= self.abort_on_check


@pytest.fixture
def fs(tmp_path):
    return FsService(cwd=str(tmp_path))


async def assert_fs_error(awaitable, code):
    with pytest.raises(FsError) as caught:
        await awaitable
    assert caught.value.code == code
    return caught.value


@pytest.mark.asyncio
async def test_resolve_preserves_display_path_but_realpaths_target_identity(tmp_path, fs):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "linked"
    try:
        os.symlink(str(real_dir), str(link_dir), target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip("symlinks unavailable: %s" % error)

    target = await fs.resolve(os.path.join("linked", "missing", "file.txt"))
    assert target.displayPath == os.path.abspath(str(link_dir / "missing" / "file.txt"))
    assert target.targetKey == os.path.join(os.path.realpath(str(real_dir)), "missing", "file.txt")

    (real_dir / "missing").mkdir()
    (real_dir / "missing" / "file.txt").write_bytes(b"data")
    assert (await fs.resolve(os.path.join("linked", "missing", "file.txt"))).targetKey == target.targetKey


@pytest.mark.asyncio
async def test_resolve_rejects_blank_and_file_ancestor(tmp_path, fs):
    await assert_fs_error(fs.resolve("   "), "FS_NOT_FOUND")
    (tmp_path / "afile").write_bytes(b"file")
    await assert_fs_error(fs.resolve(os.path.join("afile", "child.txt")), "FS_NOT_FOUND")


@pytest.mark.asyncio
async def test_resolve_process_url_and_contains_use_canonical_identity(tmp_path, fs):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "file.txt").write_bytes(b"x")
    root = await fs.resolve(".")
    child = await fs.resolve(os.path.join("nested", "file.txt"))
    outside = await fs.resolve("..")
    assert fs.processPath(child) == os.path.realpath(str(nested / "file.txt"))
    assert fs.fileUrl(child).startswith("file:")
    assert fs.contains(root, root)
    assert fs.contains(root, child)
    assert not fs.contains(root, outside)


@pytest.mark.asyncio
async def test_public_config_preserves_input_and_display_uses_path_resolve_semantics(tmp_path):
    del tmp_path
    relative_cwd = "relative-workspace"
    service = FsService(cwd=relative_cwd, diff_basis_max_bytes=1234)
    assert service.config.cwd == relative_cwd
    assert service.config.diffBasisMaxBytes == 1234
    target = await service.resolve("missing.txt")
    assert target.displayPath == os.path.abspath(os.path.join(relative_cwd, "missing.txt"))


@pytest.mark.asyncio
async def test_resolve_accepts_empty_opts_cwd_with_nullish_semantics(tmp_path, monkeypatch):
    configured = tmp_path / "configured"
    configured.mkdir()
    process_dir = tmp_path / "process"
    process_dir.mkdir()
    monkeypatch.chdir(str(process_dir))
    service = FsService(cwd=str(configured))
    target = await service.resolve("missing.txt", {"cwd": ""})
    assert target.displayPath == os.path.abspath("missing.txt")
    assert target.displayPath != os.path.join(str(configured), "missing.txt")


@pytest.mark.skipif(os.name != "nt", reason="Windows 8.3 display-path contract")
@pytest.mark.asyncio
async def test_display_path_does_not_expand_8dot3_or_change_case():
    service = FsService(cwd=r"C:\Users\ADMINI~1")
    target = await service.resolve(r"missing\CaseSensitive.txt")
    assert target.displayPath == r"C:\Users\ADMINI~1\missing\CaseSensitive.txt"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [
    ("resolve", ("a.txt", {"signal": Signal(True)})),
    ("stat", ("a.txt", Signal(True))),
    ("lstat", ("a.txt", None, Signal(True))),
    ("readText", ("a.txt", Signal(True))),
    ("readBytes", ("a.txt", Signal(True), 8)),
    ("listDir", (".", Signal(True))),
])
async def test_public_operations_honor_pre_aborted_signal(fs, method, args):
    await assert_fs_error(getattr(fs, method)(*args), "FS_ABORTED")


@pytest.mark.asyncio
async def test_stat_version_detects_same_size_rewrite_with_restored_mtime(tmp_path, fs):
    path = tmp_path / "same.txt"
    path.write_bytes(b"first")
    target = await fs.resolve("same.txt")
    before_stat = os.stat(str(path))
    before = await fs.stat(target)
    await fs.writeText(target, "other")
    os.utime(str(path), ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
    after = await fs.stat(target)
    assert before.version != after.version


@pytest.mark.asyncio
async def test_lstat_does_not_follow_final_symlink(tmp_path, fs):
    real = tmp_path / "real.txt"
    real.write_bytes(b"hello")
    link = tmp_path / "link.txt"
    try:
        os.symlink(str(real), str(link))
    except (OSError, NotImplementedError) as error:
        pytest.skip("symlinks unavailable: %s" % error)
    assert (await fs.lstat("real.txt")).type == "file"
    assert (await fs.lstat("link.txt")).type == "symlink"
    assert await fs.lstat("missing.txt") is None


@pytest.mark.asyncio
async def test_read_text_preserves_mixed_line_endings_byte_for_byte(tmp_path, fs):
    raw = b"lf\ncrlf\r\nlone-cr\rend\r\n"
    (tmp_path / "mixed.txt").write_bytes(raw)
    text = await fs.readText(await fs.resolve("mixed.txt"))
    assert text.encode("utf-8") == raw


@pytest.mark.asyncio
async def test_read_text_rejects_missing_directory_binary_and_invalid_utf8(tmp_path, fs):
    await assert_fs_error(fs.readText(await fs.resolve("missing")), "FS_NOT_FOUND")
    await assert_fs_error(fs.readText(await fs.resolve(".")), "FS_NOT_REGULAR_FILE")
    (tmp_path / "binary").write_bytes(b"a\x00b")
    await assert_fs_error(fs.readText(await fs.resolve("binary")), "FS_NOT_TEXT")
    (tmp_path / "bad").write_bytes(b"a\xffb")
    await assert_fs_error(fs.readText(await fs.resolve("bad")), "FS_NOT_TEXT")


@pytest.mark.asyncio
async def test_read_text_observes_mid_read_cancellation(tmp_path, fs):
    (tmp_path / "large.txt").write_bytes(b"x" * (256 * 1024))
    signal = CountingSignal(abort_on_check=4)
    await assert_fs_error(fs.readText(await fs.resolve("large.txt"), signal), "FS_ABORTED")


@pytest.mark.asyncio
async def test_stream_text_matches_whole_file_without_eol_normalization(tmp_path, fs):
    raw = b"one\r\ntwo\nthree\r"
    (tmp_path / "stream.txt").write_bytes(raw)
    chunks = await fs.streamText(await fs.resolve("stream.txt"))
    collected = ""
    async for chunk in chunks:
        collected += chunk
    assert collected.encode("utf-8") == raw


@pytest.mark.asyncio
async def test_read_bytes_is_binary_safe_and_enforces_inclusive_limit(tmp_path, fs):
    raw = b"a\x00b\xff"
    (tmp_path / "bytes.bin").write_bytes(raw)
    target = await fs.resolve("bytes.bin")
    assert await fs.readBytes(target, None, len(raw)) == raw
    await assert_fs_error(fs.readBytes(target, None, len(raw) - 1), "FS_TOO_LARGE")


@pytest.mark.asyncio
async def test_read_bytes_rechecks_actual_content_after_stat_race(tmp_path, fs):
    path = tmp_path / "growing.bin"
    path.write_bytes(b"1234")
    target = await fs.resolve("growing.bin")

    def grow(_target):
        path.write_bytes(b"x" * 1024)

    fs.internals.inspectReadBytesAfterStat = grow
    await assert_fs_error(fs.readBytes(target, None, 4), "FS_TOO_LARGE")


@pytest.mark.asyncio
async def test_read_bytes_observes_mid_read_cancellation(tmp_path, fs):
    size = 256 * 1024
    (tmp_path / "large.bin").write_bytes(b"x" * size)
    signal = CountingSignal(abort_on_check=3)
    await assert_fs_error(fs.readBytes(await fs.resolve("large.bin"), signal, size), "FS_ABORTED")


@pytest.mark.asyncio
async def test_list_dir_stable_metadata_targets_and_error_codes(tmp_path, fs):
    root = tmp_path / "skills"
    root.mkdir()
    (root / "dir-skill").mkdir()
    (root / "zeta.md").write_bytes(b"zeta")
    (root / "alpha.md").write_bytes(b"alpha")
    broken = root / "broken-link"
    try:
        os.symlink(str(root / "missing-target"), str(broken))
    except (OSError, NotImplementedError):
        broken = None

    entries = await fs.listDir(await fs.resolve("skills"))
    names = [entry.name for entry in entries]
    assert names == sorted(names)
    alpha = next(entry for entry in entries if entry.name == "alpha.md")
    assert alpha.type == "file" and alpha.size == 5 and alpha.version
    assert alpha.target.displayPath == os.path.abspath(str(root / "alpha.md"))
    assert alpha.target.targetKey == os.path.realpath(str(root / "alpha.md"))
    directory = next(entry for entry in entries if entry.name == "dir-skill")
    assert directory.type == "directory" and directory.size is None
    if broken is not None:
        broken_entry = next(entry for entry in entries if entry.name == "broken-link")
        assert broken_entry.type == "other" and broken_entry.version is None

    await assert_fs_error(fs.listDir(await fs.resolve("missing")), "FS_NOT_FOUND")
    await assert_fs_error(fs.listDir(await fs.resolve("skills/alpha.md")), "FS_NOT_DIRECTORY")


@pytest.mark.asyncio
@pytest.mark.parametrize("error_number", [errno.ENOENT, errno.ENOTDIR])
async def test_list_dir_maps_disappearance_after_probe_to_not_found(tmp_path, fs, monkeypatch, error_number):
    root = tmp_path / "vanishing"
    root.mkdir()
    target = await fs.resolve("vanishing")

    def disappear(_path):
        raise OSError(error_number, "vanished after probe")

    monkeypatch.setattr(fs_local_module.os, "listdir", disappear)
    await assert_fs_error(fs.listDir(target), "FS_NOT_FOUND")


@pytest.mark.asyncio
async def test_write_text_guards_versions_and_returns_normalized_diff_basis(tmp_path, fs):
    target = await fs.resolve("guarded.txt")
    created = await fs.writeText(target, "a\r\nb\r\n", {"kind": "createIfAbsent"})
    assert created.operation == "create" and created.before is None
    assert created.after == "a\nb\n"
    assert (tmp_path / "guarded.txt").read_bytes() == b"a\r\nb\r\n"

    await assert_fs_error(fs.writeText(target, "blind", {"kind": "createIfAbsent"}), "FS_NOT_OBSERVED")
    stale = created.version
    (tmp_path / "guarded.txt").write_bytes(b"external change")
    await assert_fs_error(
        fs.writeText(target, "ours", {"kind": "replaceIfVersion", "version": stale}),
        "FS_STALE_VERSION",
    )
    current = await fs.stat(target)
    updated = await fs.writeText(
        target,
        "external CHANGE",
        {"kind": "replaceIfVersion", "version": current.version},
    )
    assert updated.operation == "update"
    assert updated.before == "external change"
    assert updated.version == (await fs.stat(target)).version


@pytest.mark.asyncio
async def test_write_text_binary_prior_is_undiffable_and_diff_limit_is_exclusive(tmp_path):
    fs = FsService(cwd=str(tmp_path), diff_basis_max_bytes=4)
    (tmp_path / "binary").write_bytes(b"\x00a")
    binary = await fs.writeText(await fs.resolve("binary"), "ok")
    assert binary.before is None
    (tmp_path / "edge").write_bytes(b"1234")
    edge = await fs.writeText(await fs.resolve("edge"), "new")
    assert edge.before is None
    (tmp_path / "small").write_bytes(b"123")
    small = await fs.writeText(await fs.resolve("small"), "new")
    assert small.before == "123"


@pytest.mark.asyncio
async def test_diff_basis_uses_chunked_reads_and_observes_mid_read_cancel(tmp_path, fs, monkeypatch):
    path = tmp_path / "large-before.txt"
    path.write_bytes(b"x" * (256 * 1024))
    target = await fs.resolve("large-before.txt")
    signal = Signal(False)
    read_sizes = []
    real_open = builtins.open

    class ObservedReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def read(self, size=-1):
            read_sizes.append(size)
            data = self.handle.read(size)
            signal.aborted = True
            return data

    def observed_open(name, mode="r", *args, **kwargs):
        handle = real_open(name, mode, *args, **kwargs)
        return ObservedReader(handle) if mode == "rb" else handle

    monkeypatch.setattr(builtins, "open", observed_open)
    await assert_fs_error(fs.writeText(target, "new", None, signal), "FS_ABORTED")
    assert read_sizes and all(0 < size <= fs_local_module.READ_CHUNK_BYTES for size in read_sizes)
    assert path.read_bytes() == b"x" * (256 * 1024)


@pytest.mark.asyncio
async def test_edit_text_uses_chunked_reads_and_observes_mid_read_cancel(tmp_path, fs, monkeypatch):
    path = tmp_path / "large-edit.txt"
    path.write_bytes(b"a" * (256 * 1024))
    target = await fs.resolve("large-edit.txt")
    signal = Signal(False)
    read_sizes = []
    real_open = builtins.open

    class ObservedReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def read(self, size=-1):
            read_sizes.append(size)
            data = self.handle.read(size)
            signal.aborted = True
            return data

    def observed_open(name, mode="r", *args, **kwargs):
        handle = real_open(name, mode, *args, **kwargs)
        return ObservedReader(handle) if mode == "rb" else handle

    monkeypatch.setattr(builtins, "open", observed_open)
    await assert_fs_error(
        fs.editText(target, {"oldString": "a", "newString": "b", "replaceAll": True}, None, signal),
        "FS_ABORTED",
    )
    assert read_sizes and all(0 < size <= fs_local_module.READ_CHUNK_BYTES for size in read_sizes)
    assert path.read_bytes() == b"a" * (256 * 1024)


@pytest.mark.asyncio
async def test_atomic_write_preserves_existing_mode_and_private_new_file_mode(tmp_path, fs):
    if os.name == "nt":
        pytest.skip("POSIX mode assertions do not describe Windows DACL semantics")
    path = tmp_path / "mode.txt"
    path.write_bytes(b"old")
    os.chmod(str(path), 0o640)
    await fs.writeText(await fs.resolve("mode.txt"), "new")
    assert stat_module.S_IMODE(os.stat(str(path)).st_mode) == 0o640
    await fs.writeText(await fs.resolve("new.txt"), "created")
    assert stat_module.S_IMODE(os.stat(str(tmp_path / "new.txt")).st_mode) == 0o600
    assert not [name for name in os.listdir(str(tmp_path)) if name.endswith(".tmpdir")]


@pytest.mark.skipif(os.name != "nt", reason="Windows native publication boundary")
@pytest.mark.asyncio
@pytest.mark.parametrize("failing_boundary", ["copy", "replace"])
async def test_windows_native_failure_preserves_target_and_cleans_staging(tmp_path, fs, failing_boundary):
    path = tmp_path / "protected.txt"
    path.write_bytes(b"old")
    target = await fs.resolve("protected.txt")
    fs.internals.platform = "win32"

    def denied(*_args):
        raise OSError(errno.EACCES, "%s denied" % failing_boundary)

    fs.internals.copyFileDacl = denied if failing_boundary == "copy" else (lambda *_args: None)
    fs.internals.replaceFile = denied if failing_boundary == "replace" else (lambda *_args: None)
    with pytest.raises(OSError) as caught:
        await fs.writeText(target, "new")
    assert caught.value.errno == errno.EACCES
    assert path.read_bytes() == b"old"
    assert not [name for name in os.listdir(str(tmp_path)) if name.endswith(".tmpdir")]


@pytest.mark.asyncio
async def test_write_text_pre_aborted_leaves_target_unchanged(tmp_path, fs):
    path = tmp_path / "keep.txt"
    path.write_bytes(b"keep")
    target = await fs.resolve("keep.txt")
    await assert_fs_error(fs.writeText(target, "replace", None, Signal(True)), "FS_ABORTED")
    assert path.read_bytes() == b"keep"


@pytest.mark.asyncio
async def test_write_text_observes_mid_write_cancellation_and_cleans_staging(tmp_path, fs):
    target = await fs.resolve("cancelled.txt")
    signal = CountingSignal(abort_on_check=5)
    await assert_fs_error(fs.writeText(target, "x" * (256 * 1024), None, signal), "FS_ABORTED")
    assert not (tmp_path / "cancelled.txt").exists()
    assert not [name for name in os.listdir(str(tmp_path)) if name.endswith(".tmpdir")]


@pytest.mark.asyncio
async def test_create_if_absent_preserves_competitor_created_after_probe(tmp_path, fs):
    path = tmp_path / "raced.txt"
    target = await fs.resolve("raced.txt")

    def create_competitor(_paths):
        path.write_bytes(b"competitor")

    fs.internals.inspectTemp = create_competitor
    await assert_fs_error(fs.writeText(target, "ours", {"kind": "createIfAbsent"}), "FS_NOT_OBSERVED")
    assert path.read_bytes() == b"competitor"
    assert not [name for name in os.listdir(str(tmp_path)) if name.endswith(".tmpdir")]


@pytest.mark.asyncio
async def test_two_concurrent_guarded_writes_have_one_winner(tmp_path, fs):
    (tmp_path / "race.txt").write_bytes(b"base")
    target = await fs.resolve("race.txt")
    version = (await fs.stat(target)).version
    results = await asyncio.gather(
        fs.writeText(target, "one", {"kind": "replaceIfVersion", "version": version}),
        fs.writeText(target, "two", {"kind": "replaceIfVersion", "version": version}),
        return_exceptions=True,
    )
    assert len([value for value in results if not isinstance(value, Exception)]) == 1
    failures = [value for value in results if isinstance(value, Exception)]
    assert len(failures) == 1
    assert isinstance(failures[0], FsError) and failures[0].code == "FS_STALE_VERSION"
    assert not fs._locks


@pytest.mark.asyncio
async def test_symlink_aliases_share_identity_and_writes_keep_link(tmp_path, fs):
    real = tmp_path / "real.txt"
    real.write_bytes(b"hello")
    link = tmp_path / "link.txt"
    try:
        os.symlink(str(real), str(link))
    except (OSError, NotImplementedError) as error:
        pytest.skip("symlinks unavailable: %s" % error)
    via_real = await fs.resolve("real.txt")
    via_link = await fs.resolve("link.txt")
    assert via_real.targetKey == via_link.targetKey
    await fs.writeText(via_link, "bye", {"kind": "replaceIfVersion", "version": (await fs.stat(via_real)).version})
    assert os.path.islink(str(link))
    assert real.read_bytes() == b"bye"


@pytest.mark.asyncio
async def test_plugin_owns_and_withdraws_fs_service(tmp_path):
    ctx = Context()
    await ctx.registry.plugin(FsLocalPlugin, config={"cwd": str(tmp_path)}, parent_ctx=ctx)
    assert isinstance(ctx.get("fs"), FsService)
    assert await ctx.registry.unload_plugin("fs-local")
    assert ctx.get("fs", None, strict=False) is None


def test_diff_basis_limit_validation(tmp_path):
    for value in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match="diffBasisMaxBytes"):
            FsService(cwd=str(tmp_path), diff_basis_max_bytes=value)


@pytest.mark.skipif(os.name != "nt", reason="Win32 native path contract")
def test_win32_security_apis_receive_namespaced_drive_and_unc_paths(monkeypatch):
    calls = []

    class FakeFunction:
        def __init__(self, name):
            self.name = name

        def __call__(self, *args):
            calls.append((self.name, args))
            if self.name == "GetFileSecurityW":
                args[4]._obj.value = 8
                return 0 if args[2] is None else 1
            return 1

    class FakeLibrary:
        def __init__(self, names):
            for name in names:
                setattr(self, name, FakeFunction(name))

    def fake_win_dll(name, use_last_error=False):
        assert use_last_error is True
        if name == "advapi32":
            return FakeLibrary(["GetFileSecurityW", "SetFileSecurityW"])
        if name == "kernel32":
            return FakeLibrary(["ReplaceFileW"])
        raise AssertionError(name)

    import ctypes
    monkeypatch.setattr(ctypes, "WinDLL", fake_win_dll)
    FsService._copy_windows_dacl(r"C:\work\source.txt", r"\\server\share\temp.txt")
    FsService._replace_windows(r"C:\work\target.txt", r"\\?\C:\work\replacement.txt")

    get_calls = [args for name, args in calls if name == "GetFileSecurityW"]
    set_calls = [args for name, args in calls if name == "SetFileSecurityW"]
    replace_calls = [args for name, args in calls if name == "ReplaceFileW"]
    assert all(args[0] == r"\\?\C:\work\source.txt" for args in get_calls)
    assert set_calls[0][0] == r"\\?\UNC\server\share\temp.txt"
    assert replace_calls[0][0] == r"\\?\C:\work\target.txt"
    assert replace_calls[0][1] == r"\\?\C:\work\replacement.txt"


@pytest.mark.skipif(os.name != "nt", reason="Win32 namespaced path helper")
def test_namespaced_path_preserves_existing_prefix_and_handles_unc():
    assert fs_local_module._to_namespaced_path(r"C:\work\file.txt") == r"\\?\C:\work\file.txt"
    assert fs_local_module._to_namespaced_path(r"\\server\share\file.txt") == r"\\?\UNC\server\share\file.txt"
    assert fs_local_module._to_namespaced_path(r"\\?\C:\work\file.txt") == r"\\?\C:\work\file.txt"
    assert fs_local_module._to_namespaced_path(r"\\?\UNC\server\share\file.txt") == r"\\?\UNC\server\share\file.txt"


@pytest.mark.skipif(os.name != "nt", reason="Win32 extended-length ordinary I/O")
@pytest.mark.asyncio
async def test_atomic_write_passes_namespaced_paths_to_ordinary_windows_io(tmp_path, fs, monkeypatch):
    observed = {"makedirs": [], "open": [], "replace": [], "rmtree": []}
    real_makedirs = os.makedirs
    real_open = os.open
    real_replace = os.replace
    real_rmtree = fs_local_module.shutil.rmtree

    def observed_makedirs(path, *args, **kwargs):
        observed["makedirs"].append(path)
        return real_makedirs(path, *args, **kwargs)

    def observed_os_open(path, *args, **kwargs):
        observed["open"].append(path)
        return real_open(path, *args, **kwargs)

    def observed_replace(source, destination, *args, **kwargs):
        observed["replace"].extend([source, destination])
        return real_replace(source, destination, *args, **kwargs)

    def observed_rmtree(path, *args, **kwargs):
        observed["rmtree"].append(path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(fs_local_module.os, "makedirs", observed_makedirs)
    monkeypatch.setattr(fs_local_module.os, "open", observed_os_open)
    monkeypatch.setattr(fs_local_module.os, "replace", observed_replace)
    monkeypatch.setattr(fs_local_module.shutil, "rmtree", observed_rmtree)
    await fs.writeText(await fs.resolve("long-path.txt"), "content")
    for operation in observed.values():
        assert operation
        assert all(path.startswith("\\\\?\\") for path in operation)
