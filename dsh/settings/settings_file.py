"""Comment-preserving file-backed settings provider."""

import copy
import errno
import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.plugin import Plugin
from dsh.settings.provider import (
    SettingsConflictError, SettingsDescriptor, SettingsProvider,
    SettingsRegistration, SettingsScope, deep_equal_json,
)


FORMATS = {".yaml": "yaml", ".yml": "yaml", ".json": "json"}
name = "settings-file"


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: _UniqueKeySafeLoader, node: Any,
                              deep: bool = False) -> Dict[Any, Any]:
    keys = set()
    for key_node, _value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node, deep=False)
        try:
            duplicate = key in keys
        except TypeError:
            duplicate = False
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found duplicate key %r" % key, key_node.start_mark)
        try:
            keys.add(key)
        except TypeError:
            pass
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


class ResolvedSpec:
    def __init__(self, filename: str, format_type: str, watch: bool,
                 debounce_ms: int):
        self.filename = filename
        self.format = format_type
        self.watch = watch
        self.debounce_ms = debounce_ms


def resolve_spec(config: Union[dict, Any]) -> ResolvedSpec:
    cfg = config if isinstance(config, dict) else (getattr(config, "__dict__", {}) or {})
    raw_path = cfg.get("path")
    configured_home = cfg.get("dshHome")
    if isinstance(configured_home, str):
        configured_home = os.path.expanduser(configured_home)
    filename = os.path.abspath(
        raw_path if raw_path is not None else
        os.path.join(resolve_dsh_home(configured_home), "settings.yaml")
    )
    extension = os.path.splitext(filename)[1].lower()
    format_type = FORMATS.get(extension)
    if format_type is None:
        raise ValueError('settings-file: extension "%s" is not supported (use .yaml, .yml, or .json)' % extension)
    watch = cfg.get("watch", True)
    if not isinstance(watch, bool):
        raise TypeError("settings-file: watch must be a boolean")
    debounce_ms = cfg.get("debounceMs", 100)
    if (isinstance(debounce_ms, bool)
            or not isinstance(debounce_ms, (int, float))
            or debounce_ms < 0):
        raise ValueError("settings-file: debounceMs must be a non-negative number")
    return ResolvedSpec(filename, format_type, watch, int(debounce_ms))


def is_map_like(value: Any) -> bool:
    return isinstance(value, dict)


def patch_node(document: dict, path: List[str], current: Any,
               next_value: Any) -> None:
    if is_map_like(current) and is_map_like(next_value):
        target = document
        for part in path:
            target = target.setdefault(part, {})
        for key in list(current):
            if key not in next_value:
                target.pop(key, None)
        for key, value in next_value.items():
            patch_node(document, path + [key], current.get(key), value)
        return
    if not deep_equal_json(current, next_value):
        target = document
        for part in path[:-1]:
            target = target.setdefault(part, {})
        if path:
            target[path[-1]] = copy.deepcopy(next_value)


class _WriterLock:
    def __init__(self, path: str, timeout: float = 2.0):
        self.path = path
        self.timeout = timeout
        self.fd = None

    def __enter__(self) -> "_WriterLock":
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(self.fd, ("%d\n" % os.getpid()).encode("ascii"))
                return self
            except OSError as error:
                if error.errno != errno.EEXIST:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("settings-file: timed out waiting for the writer lock %s" % self.path)
                time.sleep(0.025)

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        try:
            if self.fd is not None:
                os.close(self.fd)
        finally:
            self.fd = None
            try:
                os.remove(self.path)
            except OSError as error:
                if error.errno != errno.ENOENT:
                    raise


def _atomic_write(filename: str, text: str) -> None:
    directory = os.path.dirname(filename) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".%s." % os.path.basename(filename),
                                     suffix=".tmp", dir=directory)
    try:
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            fd = -1
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, filename)
        try:
            os.chmod(filename, 0o600)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.remove(temporary)
        except OSError as error:
            if error.errno != errno.ENOENT:
                raise


def _yaml_key_line(line: str) -> Optional[Tuple[int, str]]:
    indent = len(line) - len(line.lstrip(" "))
    source = line[indent:]
    if not source or source.startswith(("#", "-", "?")):
        return None
    quote = None
    escaped = False
    for index, char in enumerate(source):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
        elif quote is not None:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == ":" and (index + 1 == len(source)
                              or source[index + 1].isspace()):
            try:
                parsed = yaml.safe_load(source[:index])
            except Exception:
                return None
            return (indent, str(parsed)) if isinstance(parsed, str) else None
    return None


def _yaml_key_lines(text: str) -> Tuple[List[str], Dict[Tuple[str, ...], Tuple[int, int, int]]]:
    lines = text.splitlines(True)
    entries = []
    stack: List[Tuple[int, str]] = []
    for index, line in enumerate(lines):
        parsed = _yaml_key_line(line)
        if parsed is None:
            continue
        indent, key = parsed
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = tuple([entry[1] for entry in stack] + [key])
        entries.append((path, index, indent))
        stack.append((indent, key))
    spans = {}
    for position, (path, start, indent) in enumerate(entries):
        end = len(lines)
        for _path, other_start, other_indent in entries[position + 1:]:
            if other_indent <= indent:
                end = other_start
                break
        while end > start + 1 and (lines[end - 1].strip() == ""
                                   or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        spans[path] = (start, end, indent)
    return lines, spans


def _dump_key_block(key: str, value: Any, indent: int) -> List[str]:
    dumped = yaml.safe_dump({key: value}, default_flow_style=False,
                            allow_unicode=True, sort_keys=False, width=4096)
    prefix = " " * indent
    return [prefix + line if line.strip() else line
            for line in dumped.splitlines(True)]


def _diff_paths(current: Any, next_value: Any,
                path: Tuple[str, ...]) -> List[Tuple[str, Tuple[str, ...], Any]]:
    if isinstance(current, dict) and isinstance(next_value, dict):
        changes = []
        for key in current:
            if key not in next_value:
                changes.append(("delete", path + (key,), None))
        for key, value in next_value.items():
            if key not in current:
                changes.append(("set", path + (key,), value))
            else:
                changes.extend(_diff_paths(current[key], value, path + (key,)))
        return changes
    return [] if deep_equal_json(current, next_value) else [("set", path, next_value)]


def _patch_yaml_text(text: Optional[str], namespace: str,
                     current: Any, next_value: Dict[str, Any]) -> str:
    if text is None:
        return yaml.safe_dump({namespace: next_value}, default_flow_style=False,
                              allow_unicode=True, sort_keys=False, width=4096)
    lines, spans = _yaml_key_lines(text)
    namespace_path = (namespace,)
    if namespace_path not in spans:
        suffix = "" if text == "" or text.endswith("\n") else "\n"
        return text + suffix + "".join(_dump_key_block(namespace, next_value, 0))
    namespace_start, namespace_end, namespace_indent = spans[namespace_path]
    namespace_line = lines[namespace_start]
    value_source = namespace_line[namespace_line.find(":") + 1:].strip()
    if value_source.startswith(("{", "[", "*")):
        block = _dump_key_block(namespace, next_value, namespace_indent)
        inline_comment = namespace_line.find(" #")
        if inline_comment >= 0:
            block[0] = (block[0].rstrip("\n")
                        + namespace_line[inline_comment:].rstrip("\n") + "\n")
        lines[namespace_start:namespace_end] = block
        return "".join(lines)
    edits = []
    for kind, path, value in _diff_paths(current, next_value, namespace_path):
        span = spans.get(path)
        if span is None:
            parent_span = spans.get(path[:-1], spans[namespace_path])
            edits.append((parent_span[1], parent_span[1],
                          _dump_key_block(path[-1], value, parent_span[2] + 2)))
            continue
        start, end, indent = span
        if kind == "delete":
            edits.append((start, end, []))
        else:
            block = _dump_key_block(path[-1], value, indent)
            inline = lines[start].find(" #")
            if inline >= 0 and len(block) == 1:
                block[0] = block[0].rstrip("\n") + lines[start][inline:].rstrip("\n") + "\n"
            edits.append((start, end, block))
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        lines[start:end] = replacement
    return "".join(lines)


class FileSettingsProvider(SettingsProvider):
    def __init__(self, ctx: Optional[Any] = None,
                 config: Optional[Union[dict, str]] = None,
                 settings_file: Optional[str] = None,
                 watch: Optional[bool] = None,
                 debounce_ms: Optional[int] = None):
        if ctx is None:
            from dsh.cordis.context import Context
            ctx = Context()
        cfg = {"path": config} if isinstance(config, str) else dict(config or {})
        if settings_file is not None:
            cfg["path"] = settings_file
        if watch is not None:
            cfg["watch"] = watch
        if debounce_ms is not None:
            cfg["debounceMs"] = debounce_ms
        self.config = cfg
        self.spec = resolve_spec(cfg)
        self.filepath = self.spec.filename
        self.lock_path = self.filepath + ".lock"
        self._operation_lock = threading.RLock()
        self._text: Optional[str] = None
        self._closed = False
        self._thread: Optional[threading.Thread] = None
        self._watch_signature: Any = None
        super().__init__(ctx)
        self._document = self.load()
        self._watch_signature = self._signature()
        if self.spec.watch:
            self._start_watcher()

    @property
    def writable(self) -> bool:
        return True

    @property
    def document_path(self) -> str:
        return self.spec.filename

    @property
    def _data(self) -> Dict[str, Any]:
        return self._document

    @_data.setter
    def _data(self, value: Dict[str, Any]) -> None:
        self._document = value

    @property
    def _revisions(self) -> Dict[str, int]:
        return {key: value.revision for key, value in self._registrations.items()}

    def parse(self, text: str) -> Dict[str, Any]:
        try:
            root = ({} if text.strip() == "" else json.loads(text)) if self.spec.format == "json" else yaml.load(
                text, Loader=_UniqueKeySafeLoader)
        except Exception as error:
            mark = getattr(error, "problem_mark", None)
            location = (" at line %d, column %d" % (mark.line + 1, mark.column + 1)
                        if mark is not None else "")
            raise ValueError("settings-file: invalid document at %s: %s%s"
                             % (self.spec.filename, error.__class__.__name__, location))
        if root is None:
            return {}
        if not isinstance(root, dict):
            raise TypeError("settings-file: %s must be a map of namespace sections" % self.spec.filename)
        return dict(root)

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.spec.filename, "r", encoding="utf-8") as stream:
                text = stream.read()
        except OSError as error:
            if error.errno != errno.ENOENT:
                raise
            self._text = None
            return {}
        document = self.parse(text)
        self._text = text
        return document

    def prepare_document(self) -> str:
        with self._operation_lock:
            directory = os.path.dirname(self.spec.filename) or "."
            os.makedirs(directory, mode=0o700, exist_ok=True)
            with _WriterLock(self.lock_path):
                try:
                    fd = os.open(self.spec.filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except OSError as error:
                    if error.errno == errno.EEXIST:
                        return self.spec.filename
                    raise
                with os.fdopen(fd, "w", encoding="utf-8"):
                    pass
                self._text = ""
                self._watch_signature = self._signature()
                if not self._closed:
                    self.publish({})
        return self.spec.filename

    def _persist_section(self, namespace: str, section: Dict[str, Any]) -> None:
        with self._operation_lock:
            directory = os.path.dirname(self.spec.filename) or "."
            os.makedirs(directory, mode=0o700, exist_ok=True)
            with _WriterLock(self.lock_path):
                self.reconcile_from_disk()
                current = self._document.get(namespace)
                if self.spec.format == "json":
                    document = copy.deepcopy(self._document)
                    document[namespace] = copy.deepcopy(section)
                    output = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
                else:
                    output = _patch_yaml_text(self._text, namespace, current, section)
                self.parse(output)
                _atomic_write(self.spec.filename, output)
                with open(self.spec.filename, "r", encoding="utf-8") as stream:
                    persisted = stream.read()
                self.parse(persisted)
                self._text = persisted
                self._watch_signature = self._signature()

    def reconcile_from_disk(self) -> None:
        if self._closed:
            return
        try:
            with open(self.spec.filename, "r", encoding="utf-8") as stream:
                text = stream.read()
        except OSError as error:
            if error.errno != errno.ENOENT:
                raise
            text = None
        if text == self._text or self._closed:
            return
        if text is None:
            self._text = None
            self.publish({})
            return
        document = self.parse(text)
        self._text = text
        self.publish(document, source="provider")

    def refresh(self) -> None:
        if self._closed:
            return
        try:
            with self._operation_lock:
                self.reconcile_from_disk()
        except Exception as error:
            if getattr(error, "code", None) == "INVARIANT":
                raise
            self._log("warn", "settings-file: reload failed at %s; keeping the last good document: %s"
                      % (self.spec.filename, error))

    def _signature(self) -> Any:
        try:
            stat = os.stat(self.spec.filename)
            return (getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000)), stat.st_size)
        except OSError as error:
            if error.errno == errno.ENOENT:
                return None
            raise

    def _start_watcher(self) -> None:
        interval = max(0.01, min(max(self.spec.debounce_ms, 1) / 1000.0, 0.1))

        def watch_loop() -> None:
            while not self._closed:
                try:
                    signature = self._signature()
                    if signature != self._watch_signature:
                        if self.spec.debounce_ms:
                            time.sleep(self.spec.debounce_ms / 1000.0)
                        if self._closed:
                            break
                        self.refresh()
                        self._watch_signature = self._signature()
                except Exception as error:
                    self._log("warn", "settings-file: watcher error on %s: %s"
                              % (self.spec.filename, error))
                time.sleep(interval)

        self._thread = threading.Thread(target=watch_loop, name="settings-file-watch", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._closed = True
        self._stopped = True
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        with self._operation_lock:
            pass

    def get_setting(self, namespace: str, key: str, default: Any = None) -> Any:
        section = self.get(namespace)
        return section.get(key, default) if isinstance(section, dict) else default

    def set_setting(self, namespace: str, key: str, value: Any,
                    save_to_disk: bool = True) -> None:
        if namespace in self._registrations:
            self.update(namespace, {key: value})
            return
        section = copy.deepcopy(self._document.get(namespace, {}))
        if not isinstance(section, dict):
            section = {}
        section[key] = value
        if save_to_disk:
            self._persist_section(namespace, section)
        self._document[namespace] = section

    def get_revision(self, namespace: str) -> int:
        registration = self._registrations.get(namespace)
        return registration.revision if registration is not None else 1

    def get_section(self, namespace: str) -> Dict[str, Any]:
        section = self.get(namespace)
        return dict(section) if isinstance(section, dict) else {}

    def save(self) -> None:
        with self._operation_lock:
            directory = os.path.dirname(self.spec.filename) or "."
            os.makedirs(directory, mode=0o700, exist_ok=True)
            with _WriterLock(self.lock_path):
                output = (json.dumps(self._document, indent=2, ensure_ascii=False) + "\n"
                          if self.spec.format == "json" else
                          yaml.safe_dump(self._document, default_flow_style=False,
                                         allow_unicode=True, sort_keys=False, width=4096))
                _atomic_write(self.spec.filename, output)
                self._text = output
                self._watch_signature = self._signature()


SettingsService = FileSettingsProvider


class SettingsFilePlugin(Plugin):
    id = "settings-file"
    name = "settings-file"

    def apply(self, ctx: Any) -> None:
        service = FileSettingsProvider(ctx=ctx, config=self.config or {})
        ctx.effect(service.close, label="settings-file.close")
        ctx.emit("settings/ready", service)


__all__ = [
    "FileSettingsProvider", "ResolvedSpec", "SettingsConflictError",
    "SettingsDescriptor", "SettingsFilePlugin", "SettingsProvider",
    "SettingsRegistration", "SettingsScope", "SettingsService",
    "name", "patch_node", "resolve_spec",
]
