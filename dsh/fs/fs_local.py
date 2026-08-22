import os
import pathlib
import urllib.parse
from typing import Any, Dict, List, Optional, Union
from dsh.cordis.plugin import Plugin


class FsError(Exception):
    """Typed filesystem error matching TS FsError."""
    def __init__(self, message: str, code: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.cause = cause


class FsTarget:
    """Resolved filesystem target key and display path."""
    def __init__(self, target_key: str, display_path: str):
        self.targetKey = target_key
        self.displayPath = display_path

    @property
    def target_key(self) -> str:
        return self.targetKey

    @property
    def display_path(self) -> str:
        return self.displayPath

    def __repr__(self) -> str:
        return f"FsTarget(targetKey={self.targetKey!r}, displayPath={self.displayPath!r})"


class FsInfo:
    """Target metadata returned by stat."""
    def __init__(self, version: str, type_: str, size: Optional[int] = None):
        self.version = version
        self.type = type_  # 'file' | 'directory' | 'other'
        self.size = size


class FsPathInfo:
    """Path entry metadata returned by lstat."""
    def __init__(self, version: str, type_: str, size: Optional[int] = None):
        self.version = version
        self.type = type_  # 'file' | 'directory' | 'symlink' | 'other'
        self.size = size


class FsDirEntry:
    """Directory entry returned by listDir."""
    def __init__(
        self,
        name: str,
        type_: str,
        target: FsTarget,
        version: Optional[str] = None,
        size: Optional[int] = None,
    ):
        self.name = name
        self.type = type_
        self.target = target
        self.version = version
        self.size = size


class FsWriteOutcome:
    """Outcome of full-file writeText."""
    def __init__(self, operation: str, version: str, before: Optional[str], after: str):
        self.operation = operation  # 'create' | 'update'
        self.version = version
        self.before = before
        self.after = after


class FsEditOutcome:
    """Outcome of literal editText."""
    def __init__(self, version: str, before: str, after: str):
        self.version = version
        self.before = before
        self.after = after


class FsService:
    """
    Filesystem service registered at `ctx.fs`.
    Provides safe workspace filesystem access matching TypeScript FileSystem / LocalFileSystem.
    """

    def __init__(self, cwd: Optional[str] = None, diff_basis_max_bytes: int = 10 * 1024 * 1024):
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.diff_basis_max_bytes = diff_basis_max_bytes

    @property
    def sandboxMode(self) -> Optional[str]:
        return None

    @property
    def sandbox_mode(self) -> Optional[str]:
        return None

    def resolve_path(self, path_str: str) -> str:
        p = pathlib.Path(path_str)
        if not p.is_absolute():
            p = pathlib.Path(self.cwd) / p
        try:
            return str(p.resolve())
        except OSError:
            return str(p.absolute())

    async def resolve(self, path: str, opts: Optional[Dict[str, Any]] = None) -> FsTarget:
        base_cwd = (opts.get("cwd") if opts and "cwd" in opts else None) or self.cwd
        p = pathlib.Path(path)
        if not p.is_absolute():
            p = pathlib.Path(base_cwd) / p
        try:
            real_p = str(p.resolve())
        except OSError:
            real_p = str(p.absolute())
        return FsTarget(target_key=real_p, display_path=real_p)

    def processPath(self, target: FsTarget) -> str:
        return target.targetKey

    def process_path(self, target: FsTarget) -> str:
        return target.targetKey

    def fileUrl(self, target: FsTarget) -> str:
        p = self.processPath(target)
        return pathlib.Path(p).as_uri()

    def file_url(self, target: FsTarget) -> str:
        return self.fileUrl(target)

    def contains(self, parent: Union[FsTarget, str], child: Union[FsTarget, str]) -> bool:
        parent_path = parent.targetKey if isinstance(parent, FsTarget) else self.resolve_path(parent)
        child_path = child.targetKey if isinstance(child, FsTarget) else self.resolve_path(child)
        try:
            rel = os.path.relpath(child_path, parent_path)
            return rel == "." or (not rel.startswith("..") and not os.path.isabs(rel))
        except ValueError:
            return False

    def _get_version(self, path_str: str) -> str:
        try:
            st = os.stat(path_str)
            return f"{st.st_mtime_ns}:{st.st_size}"
        except OSError:
            return f"missing:{path_str}"

    async def stat(self, target: Union[FsTarget, str], signal: Optional[Any] = None) -> Optional[FsInfo]:
        path_str = target.targetKey if isinstance(target, FsTarget) else self.resolve_path(target)
        if not os.path.exists(path_str):
            return None
        try:
            st = os.stat(path_str)
            version = f"{st.st_mtime_ns}:{st.st_size}"
            if os.path.isfile(path_str):
                t = "file"
            elif os.path.isdir(path_str):
                t = "directory"
            else:
                t = "other"
            return FsInfo(version=version, type_=t, size=st.st_size if t == "file" else None)
        except OSError:
            return None

    async def lstat(self, path: str, opts: Optional[Dict[str, Any]] = None, signal: Optional[Any] = None) -> Optional[FsPathInfo]:
        base_cwd = (opts.get("cwd") if opts and "cwd" in opts else None) or self.cwd
        p = pathlib.Path(path)
        if not p.is_absolute():
            p = pathlib.Path(base_cwd) / p
        full_path = str(p)
        try:
            st = os.lstat(full_path)
            version = f"{st.st_mtime_ns}:{st.st_size}"
            if os.path.islink(full_path):
                t = "symlink"
            elif os.path.isfile(full_path):
                t = "file"
            elif os.path.isdir(full_path):
                t = "directory"
            else:
                t = "other"
            return FsPathInfo(version=version, type_=t, size=st.st_size)
        except OSError:
            return None

    def exists(self, path_str: str) -> bool:
        return os.path.exists(self.resolve_path(path_str))

    def is_file(self, path_str: str) -> bool:
        return os.path.isfile(self.resolve_path(path_str))

    def is_dir(self, path_str: str) -> bool:
        return os.path.isdir(self.resolve_path(path_str))

    def read_text(self, path_str: str, encoding: str = "utf-8") -> str:
        full_path = self.resolve_path(path_str)
        with open(full_path, "r", encoding=encoding, errors="replace") as f:
            return f.read()

    async def readText(self, target: Union[FsTarget, str], signal: Optional[Any] = None) -> str:
        path_str = target.targetKey if isinstance(target, FsTarget) else self.resolve_path(target)
        return self.read_text(path_str)

    async def streamText(self, target: Union[FsTarget, str], signal: Optional[Any] = None) -> List[str]:
        content = await self.readText(target, signal)
        return [content]

    async def readBytes(self, target: Union[FsTarget, str], signal: Optional[Any] = None, max_bytes: int = 10000000) -> bytes:
        path_str = target.targetKey if isinstance(target, FsTarget) else self.resolve_path(target)
        if os.path.getsize(path_str) > max_bytes:
            raise FsError(f"file '{path_str}' exceeds maxBytes {max_bytes}", "FS_TOO_LARGE")
        with open(path_str, "rb") as f:
            return f.read()

    def write_text(self, path_str: str, content: str, encoding: str = "utf-8") -> None:
        full_path = self.resolve_path(path_str)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding=encoding) as f:
            f.write(content)

    async def writeText(
        self,
        target: Union[FsTarget, str],
        content: str,
        expected: Optional[Dict[str, Any]] = None,
        signal: Optional[Any] = None,
        sandbox_policy: Optional[Any] = None,
    ) -> FsWriteOutcome:
        path_str = target.targetKey if isinstance(target, FsTarget) else self.resolve_path(target)
        existing = await self.stat(path_str)
        if existing and existing.type != "file":
            raise FsError(f'cannot write "{path_str}": not a regular file', "FS_NOT_REGULAR_FILE")

        if expected and isinstance(expected, dict):
            kind = expected.get("kind")
            if kind == "replaceIfVersion":
                if not existing:
                    raise FsError(f'cannot write "{path_str}": file no longer exists', "FS_STALE_VERSION")
                if existing.version != expected.get("version"):
                    raise FsError(f'cannot write "{path_str}": file changed since it was read', "FS_STALE_VERSION")
            elif kind == "createIfAbsent" and existing:
                raise FsError(f'cannot overwrite existing "{path_str}" without reading it first', "FS_NOT_OBSERVED")

        before = self.read_text(path_str) if existing and existing.type == "file" else None
        self.write_text(path_str, content)
        new_stat = await self.stat(path_str)
        version = new_stat.version if new_stat else f"missing:{path_str}"
        op = "update" if existing else "create"
        normalized_content = content.replace("\r\n", "\n")
        return FsWriteOutcome(operation=op, version=version, before=before, after=normalized_content)

    async def editText(
        self,
        target: Union[FsTarget, str],
        edit: Dict[str, Any],
        expected: Optional[Dict[str, Any]] = None,
        signal: Optional[Any] = None,
        sandbox_policy: Optional[Any] = None,
    ) -> FsEditOutcome:
        path_str = target.targetKey if isinstance(target, FsTarget) else self.resolve_path(target)
        existing = await self.stat(path_str)
        if not existing:
            raise FsError(f'cannot edit "{path_str}": file changed since it was read', "FS_STALE_VERSION")
        if existing.type != "file":
            raise FsError(f'cannot edit "{path_str}": not a regular file', "FS_NOT_REGULAR_FILE")
        if expected and expected.get("version") and existing.version != expected.get("version"):
            raise FsError(f'cannot edit "{path_str}": file changed since it was read', "FS_STALE_VERSION")

        before = self.read_text(path_str)
        old_str = edit.get("oldString", edit.get("old_str", ""))
        new_str = edit.get("newString", edit.get("new_str", ""))
        replace_all = edit.get("replaceAll", edit.get("replace_all", False))

        if old_str not in before:
            raise FsError(f"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path_str}.", "FS_EDIT_NOT_FOUND")
        if not replace_all and before.count(old_str) > 1:
            raise FsError(f"No replacement was performed. Multiple occurrences of old_str `{old_str}`. Please ensure it is unique", "FS_AMBIGUOUS_EDIT")

        if replace_all:
            after = before.replace(old_str, new_str)
        else:
            after = before.replace(old_str, new_str, 1)

        self.write_text(path_str, after)
        new_stat = await self.stat(path_str)
        version = new_stat.version if new_stat else f"missing:{path_str}"
        return FsEditOutcome(version=version, before=before, after=after)

    async def listDir(self, target: Union[FsTarget, str], signal: Optional[Any] = None) -> List[FsDirEntry]:
        path_str = target.targetKey if isinstance(target, FsTarget) else self.resolve_path(target)
        if not os.path.isdir(path_str):
            raise FsError(f"Path is not a directory: {path_str}", "FS_NOT_DIRECTORY")

        entries: List[FsDirEntry] = []
        for item in sorted(os.listdir(path_str)):
            item_path = os.path.join(path_str, item)
            is_directory = os.path.isdir(item_path)
            is_file_ = os.path.isfile(item_path)
            t = "directory" if is_directory else ("file" if is_file_ else "other")
            st = await self.stat(item_path)
            child_target = FsTarget(target_key=item_path, display_path=item_path)
            entries.append(FsDirEntry(
                name=item,
                type_=t,
                target=child_target,
                version=st.version if st else None,
                size=st.size if st else None,
            ))
        return entries

    def list_dir(self, path_str: str, max_depth: int = 1) -> List[Dict[str, Any]]:
        full_path = self.resolve_path(path_str)
        if not os.path.isdir(full_path):
            raise NotADirectoryError(f"Path is not a directory: {full_path}")

        results = []
        try:
            for item in sorted(os.listdir(full_path)):
                if item.startswith('.') or item in ('node_modules', '__pycache__', '.venv'):
                    continue
                item_path = os.path.join(full_path, item)
                is_directory = os.path.isdir(item_path)
                results.append({
                    "name": item,
                    "path": item_path,
                    "type": "directory" if is_directory else "file",
                    "size": os.path.getsize(item_path) if not is_directory else 0
                })
        except PermissionError:
            pass
        return results


class FsLocalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-fs-local`: Mounts local filesystem service (`ctx.fs`).
    """

    id = "fs-local"
    name = "@deepseek-ai/dsh-fs-local"

    def apply(self, ctx: Any) -> None:
        cwd = self.config.get("cwd")
        diff_basis_max_bytes = self.config.get("diffBasisMaxBytes", 10 * 1024 * 1024)
        fs_service = FsService(cwd=cwd, diff_basis_max_bytes=diff_basis_max_bytes)
        ctx.set_service("fs", fs_service)


__all__ = [
    "FsError",
    "FsTarget",
    "FsInfo",
    "FsPathInfo",
    "FsDirEntry",
    "FsWriteOutcome",
    "FsEditOutcome",
    "FsService",
    "FsLocalPlugin",
]
