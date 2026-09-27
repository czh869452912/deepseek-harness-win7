"""
Local Service Provider for the subprocess capability seam.
1:1 parity with @deepseek-ai/dsh-subprocess-local
Python 3.8.10 compatible.
"""

import asyncio
import atexit
import json
import math
import os
import select
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
    signal_value = (sig if isinstance(sig, int)
                    else getattr(py_signal, str(sig), py_signal.SIGTERM))
    try:
        if hasattr(os, "killpg"):
            os.killpg(pid, signal_value)
            return
    except Exception:
        pass
    try:
        os.kill(pid, signal_value)
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


def _signal_aborted(signal: Any) -> bool:
    if signal is None:
        return False
    checker = getattr(signal, "is_set", None)
    return bool(checker()) if callable(checker) else bool(getattr(signal, "aborted", False))


async def _wait_for_signal(signal: Any) -> None:
    waiter = getattr(signal, "wait", None)
    if callable(waiter):
        result = waiter()
        if hasattr(result, "__await__"):
            await result
            return
    while not _signal_aborted(signal):
        await asyncio.sleep(0.015)


def _linux_group_has_live_members(process_group_id: int) -> Optional[bool]:
    """Return whether /proc shows a non-zombie member, or None if unavailable."""
    if not sys.platform.startswith("linux") or not os.path.isdir("/proc"):
        return None
    inspected = False
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join("/proc", entry, "stat"), "r", encoding="utf-8") as stat_file:
                value = stat_file.read()
            close_paren = value.rfind(")")
            fields = value[close_paren + 2:].split()
            if close_paren < 0 or len(fields) < 3:
                continue
            inspected = True
            if int(fields[2]) == process_group_id and fields[0] != "Z":
                return True
        except (OSError, ValueError):
            continue
    return False if inspected else None


def _cancel_windows_pipe_read(stream: Any) -> bool:
    if sys.platform != "win32" or stream is None:
        return False
    try:
        import ctypes
        import msvcrt
        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        cancel_io = getattr(kernel32, "CancelIoEx", None)
        if cancel_io is None:
            return False
        cancel_io.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cancel_io.restype = ctypes.c_int
        return bool(cancel_io(ctypes.c_void_p(handle), None))
    except (ImportError, OSError, ValueError):
        return False


def _consume_future(future: Any) -> None:
    try:
        future.result()
    except (asyncio.CancelledError, Exception):
        pass


class LocalSubprocessHandle(SubprocessHandle):
    """Live child process handle."""

    def __init__(self, spec: SubprocessSpawnSpec, internals: Optional[Dict[str, Any]] = None):
        if not math.isfinite(spec.graceMs) or spec.graceMs <= 0 or spec.graceMs > MAX_TIMER_DELAY_MS:
            raise ValueError(f"subprocess graceMs must be a positive finite number no greater than {MAX_TIMER_DELAY_MS}")

        if not spec.argv or not spec.argv[0]:
            raise ValueError("invalid argv: expected a non-empty program name at argv[0]")
        if _signal_aborted(spec.signal):
            raise RuntimeError("aborted before spawn: aborted")

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
            popen_kwargs = {
                "cwd": spec.cwd,
                "env": env,
                "stdin": stdin_setting,
                "stdout": stdout_setting,
                "stderr": stderr_setting,
                "creationflags": creation_flags,
            }
            if sys.platform != "win32":
                popen_kwargs["start_new_session"] = True
            self._proc = subprocess.Popen([program] + args, **popen_kwargs)
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
            self._tree_exit_observed = True
            self._abort_task = None
            self._grace_timer_handle = None
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
        self._termination_started = False
        self._collector_reads_open = True

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
        self._abort_task = (loop.create_task(self._watch_abort())
                            if spec.signal is not None else None)

    async def _watch_abort(self) -> None:
        try:
            await _wait_for_signal(self.spec.signal)
            self.terminate()
        except asyncio.CancelledError:
            return

    async def _pump_and_wait(self) -> None:
        loop = asyncio.get_event_loop()

        def read_stream(stream, collector):
            if stream and collector:
                try:
                    while self._collector_reads_open:
                        if sys.platform == "win32":
                            chunk = stream.read1(4096)
                        else:
                            readable, _writable, _errors = select.select(
                                [stream.fileno()], [], [], 0.05)
                            if not readable:
                                continue
                            chunk = os.read(stream.fileno(), 4096)
                        if not chunk:
                            break
                        if not self._collector_reads_open:
                            break
                        collector.push(chunk)
                except Exception:
                    pass
                finally:
                    try:
                        stream.close()
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
            _done, pending = await asyncio.wait(
                tasks, timeout=max(0.001, self.spec.graceMs / 1000.0))
            if pending:
                self._collector_reads_open = False
                for stream in (self._proc.stdout, self._proc.stderr):
                    _cancel_windows_pipe_read(stream)
                for task in pending:
                    task.add_done_callback(_consume_future)

        if self._stdout_collector:
            self._stdout_collector.seal()
        if self._stderr_collector:
            self._stderr_collector.seal()

        if sys.platform == "win32":
            self._tree_exit_observed = True
        elif not self._tree_alive():
            self._tree_exit_observed = True
        if self._tree_exit_observed and self._grace_timer_handle:
            self._grace_timer_handle.cancel()
            self._grace_timer_handle = None
        if self._abort_task is not None and self._abort_task is not asyncio.current_task():
            self._abort_task.cancel()

        sig_str: Optional[str] = None
        code_val: Optional[int] = exit_code
        if exit_code < 0:
            code_val = None
            try:
                sig_str = py_signal.Signals(-exit_code).name
            except (ValueError, AttributeError):
                sig_str = "SIG%d" % -exit_code

        outcome = SubprocessOutcome(exit_code=code_val, signal=sig_str)
        if not self.done.done():
            self.done.set_result(outcome)

    def terminate(self) -> None:
        if self._tree_exit_observed or self.pid <= 0 or self._termination_started:
            return
        self._termination_started = True
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
        while self._tree_alive():
            if _signal_aborted(signal):
                return False
            await asyncio.sleep(0.015)
        self._tree_exit_observed = True
        if self._grace_timer_handle is not None:
            self._grace_timer_handle.cancel()
            self._grace_timer_handle = None
        return True

    def _tree_alive(self) -> bool:
        if self._tree_exit_observed or self.pid <= 0:
            return False
        if sys.platform == "win32":
            return self._proc.poll() is None
        try:
            os.killpg(self.pid, 0)
            if self._proc.poll() is not None:
                has_live_members = _linux_group_has_live_members(self.pid)
                if has_live_members is False:
                    return False
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return self._proc.poll() is None


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
            def setup_teardown():
                atexit.register(self._terminate_all)

                async def teardown():
                    try:
                        await self._dispose_managed_processes()
                    finally:
                        atexit.unregister(self._terminate_all)

                return teardown

            ctx.effect(setup_teardown, label="local subprocess teardown")

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

    async def _dispose_managed_processes(self) -> None:
        handles = list(self.live)
        terminals = list(self.terminals)
        for handle in handles:
            handle.terminate()
        waits = []
        for handle in handles:
            async def wait_handle(current=handle):
                try:
                    await current.done
                except Exception:
                    pass
                await current.wait_for_exit()
            waits.append(wait_handle())
        for terminal in terminals:
            waits.append(terminal.terminate())
        outcomes = await asyncio.gather(*waits, return_exceptions=True) if waits else []
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        if failures:
            for handle in handles:
                try:
                    handle.terminate_for_host_exit()
                except Exception:
                    pass
            for terminal in terminals:
                try:
                    if terminal.pid > 0:
                        signal_tree(terminal.pid, "SIGKILL")
                except Exception:
                    pass
        self.live.clear()
        self.terminals.clear()
        if len(failures) == 1:
            raise failures[0]
        if failures:
            error = RuntimeError("local subprocess teardown failed: %d errors" % len(failures))
            error.errors = failures
            raise error

    async def resolve_executable(
        self,
        command: str,
        env: Optional[Dict[str, str]] = None,
        signal: Optional[Any] = None,
    ) -> str:
        if not command:
            raise ValueError("subprocess-local: executable must be non-empty")
        if _signal_aborted(signal):
            raise asyncio.CancelledError("executable resolution aborted")

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
            if _signal_aborted(signal):
                raise asyncio.CancelledError("executable resolution aborted")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

        if _signal_aborted(signal):
            raise asyncio.CancelledError("executable resolution aborted")

        raise ValueError(
            f"subprocess-local: command {json.dumps(command)} is not an executable file"
            if is_abs
            else f"subprocess-local: command {json.dumps(command)} was not found on PATH"
        )

    def _executable_candidates(self, command: str, env: Dict[str, str]) -> List[str]:
        def environment_value(name: str, default: str = "") -> str:
            exact = env.get(name)
            if exact is not None or sys.platform != "win32":
                return exact if exact is not None else default
            normalized = name.upper()
            for key, value in env.items():
                if key.upper() == normalized:
                    return value
            return default

        path_str = environment_value("PATH")
        ext_str = (environment_value("PATHEXT", ".COM;.EXE;.BAT;.CMD")
                   if sys.platform == "win32" and not os.path.splitext(command)[1]
                   else "")
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
            async def release_after_tree_exit():
                await handle.wait_for_exit()
                self.live.discard(handle)

            asyncio.ensure_future(release_after_tree_exit())

        handle.done.add_done_callback(_release)
        return handle

    async def spawn_terminal(self, spec: SubprocessTerminalSpawnSpec) -> SubprocessTerminalHandle:
        if not spec.argv or not spec.argv[0]:
            raise ValueError("subprocess-local: terminal argv must contain a program")
        if _signal_aborted(spec.signal):
            raise RuntimeError("terminal allocation aborted")
        handle = LocalTerminalHandle(spec)
        self.terminals.add(handle)

        def _release(fut):
            async def release_after_quiescence():
                await handle.terminate()
                self.terminals.discard(handle)

            release = asyncio.ensure_future(release_after_quiescence())
            release.add_done_callback(_consume_future)

        handle.done.add_done_callback(_release)
        return handle
