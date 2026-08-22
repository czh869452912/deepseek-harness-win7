"""
Local Service Provider for the subprocess capability seam.
1:1 parity with @deepseek-ai/dsh-subprocess-local
Python 3.8.10 compatible.
"""

import asyncio
import json
import os
import signal as py_signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from dsh.subprocess.collector import OutputCollector
from dsh.subprocess.service import SubprocessRuntime, scrubbed_parent_env
from dsh.subprocess.types import (
    CollectedOutput,
    SubprocessCollect,
    SubprocessCollectedOutputs,
    SubprocessHandle,
    SubprocessOutcome,
    SubprocessOutputMode,
    SubprocessOutputRead,
    SubprocessOutputReader,
    SubprocessSpawnSpec,
    SubprocessStdio,
    SubprocessTerminalForeground,
    SubprocessTerminalHandle,
    SubprocessTerminalSpawnSpec,
)

MAX_TIMER_DELAY_MS = 2147483647


def child_env(extra: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, str]:
    """Build child environment: explicit extra entries merged after scrubbed parent env."""
    env = scrubbed_parent_env()
    if not extra:
        return env

    if sys.platform != "win32":
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return env

    # Windows case-insensitive merge
    entries: Dict[str, Tuple[str, str]] = {}  # norm_key -> (actual_key, value)
    for k, v in env.items():
        entries[k.upper()] = (k, v)

    for k, v in extra.items():
        norm = k.upper()
        if v is None:
            entries.pop(norm, None)
        else:
            entries[norm] = (k, v)

    return {actual_k: val for actual_k, val in entries.values()}


def kill_group(pid: int, sig: Union[int, str]) -> None:
    """Send signal to POSIX process group or process. Never throws."""
    if pid <= 0:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(pid, sig if isinstance(sig, int) else getattr(py_signal, str(sig), py_signal.SIGTERM))
        else:
            os.kill(pid, sig if isinstance(sig, int) else getattr(py_signal, str(sig), py_signal.SIGTERM))
    except Exception:
        pass


def taskkill_process_tree(pid: int, force: bool = True) -> None:
    """Terminate Windows process tree with taskkill."""
    if pid <= 0 or sys.platform != "win32":
        return
    cmd = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        cmd.append("/F")
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def signal_tree(pid: int, sig: str) -> None:
    """Deliver signal to process tree platform-correctly."""
    if sys.platform == "win32":
        taskkill_process_tree(pid, force=True)
    else:
        kill_group(pid, sig)


class LocalSubprocessHandle(SubprocessHandle):
    """Live child process handle."""

    def __init__(self, spec: SubprocessSpawnSpec, internals: Optional[Dict[str, Any]] = None):
        if spec.graceMs <= 0 or spec.graceMs > MAX_TIMER_DELAY_MS:
            raise ValueError(f"subprocess graceMs must be a positive finite number no greater than {MAX_TIMER_DELAY_MS}")

        if not spec.argv or not spec.argv[0]:
            raise ValueError("invalid argv: expected a non-empty program name at argv[0]")

        self.spec = spec
        self.internals = internals or {}
        self.spill_dir = self.internals.get("spillDir")

        program = spec.argv[0]
        args = spec.argv[1:]
        env = child_env(spec.env)

        stdin_mode = spec.stdio.stdin
        stdout_mode = spec.stdio.stdout
        stderr_mode = spec.stdio.stderr

        stdin_setting = subprocess.DEVNULL if stdin_mode == "ignore" else subprocess.PIPE
        stdout_setting = None if stdout_mode == "inherit" else subprocess.PIPE
        stderr_setting = None if stderr_mode == "inherit" else subprocess.PIPE

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            self._proc = subprocess.Popen(
                [program] + args,
                cwd=spec.cwd,
                env=env,
                stdin=stdin_setting,
                stdout=stdout_setting,
                stderr=stderr_setting,
                creationflags=creation_flags,
            )
            self.pid = self._proc.pid
        except Exception as e:
            self.pid = -1
            loop = asyncio.get_event_loop()
            self.done = loop.create_future()
            self.done.set_exception(e)
            self.stdin = None
            self.stdout = None
            self.stderr = None
            self.collected = SubprocessCollectedOutputs()
            return

        self.stdin = self._proc.stdin if stdin_mode == "pipe" else None
        self.stdout = self._proc.stdout if stdout_mode == "pipe" else None
        self.stderr = self._proc.stderr if stderr_mode == "pipe" else None

        self._stdout_collector: Optional[OutputCollector] = None
        self._stderr_collector: Optional[OutputCollector] = None

        if isinstance(stdout_mode, SubprocessCollect):
            self._stdout_collector = OutputCollector(
                max_bytes=stdout_mode.maxBytes,
                max_spill_bytes=stdout_mode.spill.get("maxBytes") if stdout_mode.spill else None,
                label="stdout",
                spill_dir=self.spill_dir,
            )
        if isinstance(stderr_mode, SubprocessCollect):
            self._stderr_collector = OutputCollector(
                max_bytes=stderr_mode.maxBytes,
                max_spill_bytes=stderr_mode.spill.get("maxBytes") if stderr_mode.spill else None,
                label="stderr",
                spill_dir=self.spill_dir,
            )

        self.collected = SubprocessCollectedOutputs(
            stdout=self._stdout_collector,
            stderr=self._stderr_collector,
        )

        loop = asyncio.get_event_loop()
        self.done = loop.create_future()
        self._tree_exit_observed = False
        self._grace_timer_handle: Optional[asyncio.TimerHandle] = None

        # Write stdin batch data if supplied
        if isinstance(stdin_mode, dict) and "data" in stdin_mode and self._proc.stdin:
            try:
                data_bytes = stdin_mode["data"].encode("utf-8")
                self._proc.stdin.write(data_bytes)
                self._proc.stdin.flush()
                self._proc.stdin.close()
            except Exception:
                pass

        # Start background pump / wait task
        self._pump_task = loop.create_task(self._pump_and_wait())

    async def _pump_and_wait(self) -> None:
        loop = asyncio.get_event_loop()

        def read_stream(stream, collector):
            if stream and collector:
                try:
                    while True:
                        chunk = stream.read(4096)
                        if not chunk:
                            break
                        collector.push(chunk)
                except Exception:
                    pass

        # Run stream readers in threads if collectors present
        tasks = []
        if self._proc.stdout and self._stdout_collector:
            tasks.append(loop.run_in_executor(None, read_stream, self._proc.stdout, self._stdout_collector))
        if self._proc.stderr and self._stderr_collector:
            tasks.append(loop.run_in_executor(None, read_stream, self._proc.stderr, self._stderr_collector))

        # Wait process exit
        exit_code = await loop.run_in_executor(None, self._proc.wait)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if self._stdout_collector:
            self._stdout_collector.seal()
        if self._stderr_collector:
            self._stderr_collector.seal()

        self._tree_exit_observed = True
        if self._grace_timer_handle:
            self._grace_timer_handle.cancel()
            self._grace_timer_handle = None

        sig_str: Optional[str] = None
        code_val: Optional[int] = exit_code
        if exit_code < 0:
            code_val = None
            sig_str = f"SIG{-exit_code}"

        outcome = SubprocessOutcome(exit_code=code_val, signal=sig_str)
        if not self.done.done():
            self.done.set_result(outcome)

    def terminate(self) -> None:
        if self._tree_exit_observed or self.pid <= 0:
            return
        signal_tree(self.pid, "SIGTERM")
        loop = asyncio.get_event_loop()
        grace_sec = max(0.001, self.spec.graceMs / 1000.0)

        def _kill_now():
            if not self._tree_exit_observed and self.pid > 0:
                signal_tree(self.pid, "SIGKILL")

        self._grace_timer_handle = loop.call_later(grace_sec, _kill_now)

    def terminate_for_host_exit(self) -> None:
        if self.pid > 0:
            signal_tree(self.pid, "SIGKILL")

    async def wait_for_exit(self, signal: Optional[Any] = None) -> bool:
        if self._tree_exit_observed:
            return True
        try:
            await self.done
            return True
        except Exception:
            return True


class LocalTerminalHandle(SubprocessTerminalHandle):
    """Local terminal handle."""

    def __init__(self, spec: SubprocessTerminalSpawnSpec):
        self.spec = spec
        program = spec.argv[0]
        args = spec.argv[1:]
        env = child_env(spec.env)

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

        self._proc = subprocess.Popen(
            [program] + args,
            cwd=spec.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        self.pid = self._proc.pid

        loop = asyncio.get_event_loop()
        self.done = loop.create_future()
        self.output = self._proc.stdout
        self._wait_task = loop.create_task(self._wait())

    async def _wait(self) -> None:
        loop = asyncio.get_event_loop()
        code = await loop.run_in_executor(None, self._proc.wait)
        outcome = SubprocessOutcome(exit_code=code, signal=None)
        if not self.done.done():
            self.done.set_result(outcome)

    async def write(self, data: str) -> None:
        if self._proc.poll() is not None or not self._proc.stdin:
            raise RuntimeError("terminal process has exited")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._proc.stdin.write, data.encode("utf-8"))
        await loop.run_in_executor(None, self._proc.stdin.flush)

    async def inspect_foreground(self) -> Optional[SubprocessTerminalForeground]:
        return SubprocessTerminalForeground(process_group_id=self.pid, input_waiting=False)

    async def signal_foreground(self, signal_name: str) -> int:
        if self.pid > 0:
            signal_tree(self.pid, signal_name)
        return self.pid

    async def terminate(self) -> None:
        if self.pid > 0:
            signal_tree(self.pid, "SIGKILL")
        await self.done


class LocalSubprocessRuntime(SubprocessRuntime):
    """Local subprocess service implementation."""

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.live: Set[LocalSubprocessHandle] = set()
        self.terminals: Set[LocalTerminalHandle] = set()

        if hasattr(ctx, "effect"):
            def teardown():
                self._terminate_all()
            ctx.effect(teardown)

    def _terminate_all(self) -> None:
        for h in list(self.live):
            try:
                h.terminate_for_host_exit()
            except Exception:
                pass
        for t in list(self.terminals):
            try:
                if t.pid > 0:
                    signal_tree(t.pid, "SIGKILL")
            except Exception:
                pass
        self.live.clear()
        self.terminals.clear()

    async def resolve_executable(
        self,
        command: str,
        env: Optional[Dict[str, str]] = None,
        signal: Optional[Any] = None,
    ) -> str:
        if not command:
            raise ValueError("subprocess-local: executable must be non-empty")

        environment = child_env(env)
        is_abs = os.path.isabs(command)

        if not is_abs and ("/" in command or (sys.platform == "win32" and "\\" in command)):
            raise ValueError(
                f"subprocess-local: command {json.dumps(command)} is a relative path; use an absolute path or a bare PATH name"
            )

        if is_abs:
            candidates = [command]
        else:
            candidates = self._executable_candidates(command, environment)

        for candidate in candidates:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

        raise ValueError(
            f"subprocess-local: command {json.dumps(command)} is not an executable file"
            if is_abs
            else f"subprocess-local: command {json.dumps(command)} was not found on PATH"
        )

    def _executable_candidates(self, command: str, env: Dict[str, str]) -> List[str]:
        path_str = env.get("PATH", env.get("Path", ""))
        ext_str = env.get("PATHEXT", ".COM;.EXE;.BAT;.CMD") if sys.platform == "win32" and not os.path.splitext(command)[1] else ""
        extensions = ext_str.split(";") if ext_str else [""]
        directories = path_str.split(os.pathsep)

        candidates = []
        for directory in directories:
            for ext in extensions:
                candidates.append(os.path.abspath(os.path.join(directory, command + ext)))
        return candidates

    def spawn(self, spec: SubprocessSpawnSpec) -> SubprocessHandle:
        handle = LocalSubprocessHandle(spec)
        self.live.add(handle)

        def _release(fut):
            self.live.discard(handle)

        handle.done.add_done_callback(_release)
        return handle

    async def spawn_terminal(self, spec: SubprocessTerminalSpawnSpec) -> SubprocessTerminalHandle:
        if not spec.argv or not spec.argv[0]:
            raise ValueError("subprocess-local: terminal argv must contain a program")
        handle = LocalTerminalHandle(spec)
        self.terminals.add(handle)

        def _release(fut):
            self.terminals.discard(handle)

        handle.done.add_done_callback(_release)
        return handle
