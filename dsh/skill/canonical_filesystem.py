"""Filesystem skill provider with bounded polling for Python 3.8 / Win7.

Polling replaces the Node watcher dependency. Catalog/body reads still use the
mounted filesystem service; only bundled trusted-host files bypass that service.
"""
import asyncio
import logging
import os
import time
from collections import OrderedDict

import yaml

from dsh.cordis.plugin import Plugin
from dsh.skill.registry import check
from dsh.skill.skill_service import is_skill_name


def absent(error):
    return isinstance(error, (FileNotFoundError, NotADirectoryError, IsADirectoryError)) or getattr(error, "code", None) in ("FS_NOT_FOUND", "FS_NOT_DIRECTORY", "FS_NOT_REGULAR_FILE")


def parse(raw):
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if end is None:
        return None
    data = yaml.safe_load("".join(lines[1:end]))
    if not isinstance(data, dict) or not is_skill_name(data.get("name")) or not isinstance(data.get("description"), str) or not data["description"]:
        return None
    for old in ("disableModelInvocation", "modelInvocable", "userInvocable"):
        if old in data:
            raise ValueError("unsupported invocation frontmatter " + old)
    def boolean(key):
        if key not in data:
            return None
        value = data[key]
        if type(value) is bool:
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.lower() in ("true", "yes", "on", "1", "false", "no", "off", "0"):
            return value.lower() in ("true", "yes", "on", "1")
        raise ValueError("invocation frontmatter must be boolean")
    result = {"name": data["name"], "description": data["description"], "content": "".join(lines[end + 1:]).strip(),
              "invocation": {"modelInvocable": boolean("disable-model-invocation") is not True, "userInvocable": boolean("user-invocable") is not False}}
    if isinstance(data.get("whenToUse"), str) and data["whenToUse"]:
        result["whenToUse"] = data["whenToUse"]
    if isinstance(data.get("metadata"), dict):
        result["metadata"] = data["metadata"]
    return result


class FilesystemProvider:
    def __init__(self, ctx, control, config):
        self.ctx, self.control, self.config = ctx, control, config
        self.name = config.get("providerName", "filesystem")
        self.projects, self.watched, self.facts = OrderedDict(), {}, {}
        self.task = None
        for key, default in (("watchPollIntervalMs", 100), ("watchStabilityThresholdMs", 200), ("watchMaxProjects", 128)):
            value = config.get(key, default)
            if type(value) is not int or value < 1:
                raise ValueError(key + " must be a positive integer")
        self.interval = config.get("watchPollIntervalMs", 100) / 1000
        self.stability = config.get("watchStabilityThresholdMs", 200) / 1000

    async def roots(self, cwd):
        config, roots = self.config, []
        defaults = config.get("includeDefaultRoots", True)
        if defaults and cwd is not None:
            current = start = os.path.abspath(cwd)
            while True:
                fs = self.ctx.get("fs")
                try:
                    found = await fs.stat(await fs.resolve(os.path.join(current, ".git"))) is not None if fs else os.path.exists(os.path.join(current, ".git"))
                except Exception:
                    found = False
                if found:
                    break
                parent = os.path.dirname(current)
                if parent == current:
                    current = start
                    break
                current = parent
            roots.extend([(os.path.join(current, ".dsh", "skills"), "project-dsh", 100), (os.path.join(current, ".agents", "skills"), "project-agents", 200)])
            self.projects.pop(current, None)
            self.projects[current] = roots[:]
            while len(self.projects) > config.get("watchMaxProjects", 128):
                self.projects.popitem(last=False)
        fixed = [(os.path.abspath(path), "custom", 300) for path in config.get("customSkillDirs", [])]
        if defaults:
            fixed.extend([(os.path.join(config.get("dshHome") or os.environ.get("DSH_HOME") or os.path.expanduser("~/.dsh"), "skills"), "user-dsh", 400),
                          (os.path.join(config.get("agentsHome") or os.environ.get("DSH_AGENTS_HOME") or os.path.expanduser("~/.agents"), "skills"), "user-agents", 500)])
        bundled = config.get("bundledSkillDir") or (os.environ.get("DSH_BUNDLED_SKILL_DIR") if defaults else None)
        if bundled:
            fixed.append((os.path.abspath(bundled), "bundled", 600))
        roots.extend(fixed)
        self.watched = {row[0]: row for rows in list(self.projects.values()) + [fixed] for row in rows}
        self.facts = {path: fact for path, fact in self.facts.items() if path in self.watched}
        return roots

    def fingerprint(self, path):
        facts = []
        if not os.path.exists(path):
            return ()
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_symlink() and not self.config.get("watchFollowSymlinks", True):
                    continue
                candidate = os.path.join(entry.path, "SKILL.md") if entry.is_dir() else entry.path if entry.name.endswith(".md") else None
                if candidate is not None:
                    try:
                        info = os.stat(candidate)
                        facts.append((candidate, info.st_mtime_ns, info.st_size))
                    except FileNotFoundError:
                        facts.append((candidate, None, None))
        return tuple(sorted(facts))

    async def watch(self):
        pending = {}
        while not self.control.signal.aborted:
            await asyncio.sleep(self.interval)
            for path in list(self.watched):
                try:
                    fact = self.fingerprint(path)
                except OSError:
                    self.control.invalidate()
                    continue
                if fact == self.facts.get(path):
                    pending.pop(path, None)
                    continue
                candidate = pending.get(path)
                if candidate is None or candidate[0] != fact:
                    pending[path] = (fact, time.monotonic())
                elif time.monotonic() - candidate[1] >= self.stability:
                    self.facts[path] = fact
                    pending.pop(path, None)
                    self.control.invalidate()

    async def read(self, path, signal, trusted):
        check(signal)
        fs = self.ctx.get("fs")
        try:
            if fs is not None and not trusted:
                raw = await fs.readText(await fs.resolve(path), signal)
            else:
                with open(path, "r", encoding="utf-8") as stream:
                    raw = stream.read()
        except Exception as error:
            if absent(error):
                return None
            raise
        check(signal)
        try:
            return parse(raw)
        except (ValueError, yaml.YAMLError) as error:
            logging.getLogger("skills").warning("Ignoring invalid skill %s: %s", path, error)
            return None

    async def list(self, options):
        roots = await self.roots(options.get("cwd"))
        complete = True
        if self.config.get("watch", True):
            for path, _, _ in roots:
                if path not in self.facts:
                    try:
                        self.facts[path] = self.fingerprint(path)
                    except OSError:
                        complete = False
            if self.task is None:
                self.task = asyncio.create_task(self.watch())
        result = []
        for path, source, rank in roots:
            check(options.get("signal"))
            fs = self.ctx.get("fs")
            try:
                if fs is not None and source != "bundled":
                    entries = [(entry.name, entry.target.displayPath, entry.type == "directory") for entry in await fs.listDir(await fs.resolve(path))]
                else:
                    with os.scandir(path) as found:
                        entries = [(entry.name, entry.path, entry.is_dir()) for entry in found if entry.is_dir() or entry.is_file()]
            except Exception as error:
                if absent(error):
                    continue
                raise
            for name, location, directory in sorted(entries):
                if source == "user-dsh" and name == ".system":
                    continue
                if not directory and not name.endswith(".md"):
                    continue
                file_path = os.path.join(location, "SKILL.md") if directory else location
                parsed = await self.read(file_path, options.get("signal"), source == "bundled")
                if parsed is not None:
                    result.append(dict({key: value for key, value in parsed.items() if key != "content"},
                        source=source, provider=self.name, rank=rank, locator=file_path, path=file_path,
                        resourceBase={"kind": "directory", "path": os.path.dirname(file_path)}))
        return result if complete else {"candidates": result, "complete": False}

    async def get(self, candidate, options):
        parsed = await self.read(candidate["locator"], options.get("signal"), candidate["source"] == "bundled")
        return dict(parsed, source=candidate["source"], provider=self.name, path=candidate["path"], resourceBase=candidate["resourceBase"]) if parsed else None

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class CanonicalSkillFilesystem(Plugin):
    id = "skill-filesystem"
    inject = ["skills"]

    def apply(self, ctx):
        holder = []
        def create(control):
            provider = FilesystemProvider(ctx, control, self.config)
            holder.append(provider)
            return provider
        ctx.get("skills").register_provider(create)
        provider = holder[0]
        ctx.effect(lambda: provider.close, "skill filesystem watcher")
        def observed(target, observation, actor):
            name = actor.get("name") if isinstance(actor, dict) else getattr(actor, "name", None)
            if name not in ("write", "edit"):
                return
            for root in provider.watched:
                try:
                    if os.path.commonpath((root, target.displayPath)) == root:
                        provider.control.invalidate()
                        break
                except ValueError:
                    continue
        ctx.on("fs/observed", observed)
