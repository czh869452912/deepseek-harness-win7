"""
Vocabulary for the subprocess Service Definition.
1:1 parity with @deepseek-ai/dsh-subprocess/types.ts
Python 3.8.10 compatible.
"""

from abc import ABC, abstractmethod
import asyncio
from typing import Any, Dict, List, Optional, Union

DSH_ENV_PREFIX = "DSH_"


class CollectedOutput:
    def __init__(self, text: str, truncated: bool, spill_path: Optional[str] = None):
        self.text = text
        self.truncated = truncated
        self.spillPath = spill_path

    def to_dict(self) -> Dict[str, Any]:
        res = {"text": self.text, "truncated": self.truncated}
        if self.spillPath is not None:
            res["spillPath"] = self.spillPath
        return res


class SubprocessCollect:
    def __init__(self, max_bytes: int, spill: Optional[Dict[str, int]] = None):
        self.maxBytes = max_bytes
        self.spill = spill  # dict with "maxBytes"


# SubprocessStdinMode: "ignore" | "pipe" | dict {"data": str}
SubprocessStdinMode = Union[str, Dict[str, str]]

# SubprocessOutputMode: "pipe" | "inherit" | SubprocessCollect
SubprocessOutputMode = Union[str, SubprocessCollect]


class SubprocessStdio:
    def __init__(
        self,
        stdin: SubprocessStdinMode,
        stdout: SubprocessOutputMode,
        stderr: SubprocessOutputMode,
    ):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr


class SubprocessSpawnSpec:
    def __init__(
        self,
        argv: List[str],
        cwd: str,
        stdio: SubprocessStdio,
        grace_ms: int,
        signal: Optional[Any] = None,
        env: Optional[Dict[str, Optional[str]]] = None,
    ):
        self.argv = argv
        self.cwd = cwd
        self.stdio = stdio
        self.graceMs = grace_ms
        self.signal = signal
        self.env = env


class SubprocessOutcome:
    def __init__(self, exit_code: Optional[int], signal: Optional[str]):
        self.exitCode = exit_code
        self.signal = signal

    def to_dict(self) -> Dict[str, Any]:
        return {"exitCode": self.exitCode, "signal": self.signal}


class SubprocessOutputRead:
    def __init__(
        self, text: str, next_offset: int, lossy: bool, spill_path: Optional[str] = None
    ):
        self.text = text
        self.nextOffset = next_offset
        self.lossy = lossy
        self.spillPath = spill_path

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "text": self.text,
            "nextOffset": self.nextOffset,
            "lossy": self.lossy,
        }
        if self.spillPath is not None:
            res["spillPath"] = self.spillPath
        return res


class SubprocessOutputReader(ABC):
    @abstractmethod
    def read_from(self, from_byte: int) -> SubprocessOutputRead:
        pass

    def readFrom(self, from_byte: int) -> SubprocessOutputRead:
        return self.read_from(from_byte)


class SubprocessCollectedOutputs:
    def __init__(
        self,
        stdout: Optional[SubprocessOutputReader] = None,
        stderr: Optional[SubprocessOutputReader] = None,
    ):
        self.stdout = stdout
        self.stderr = stderr


class SubprocessHandle(ABC):
    pid: int
    stdin: Optional[Any]
    stdout: Optional[Any]
    stderr: Optional[Any]
    collected: SubprocessCollectedOutputs
    done: asyncio.Future  # Future resolving to SubprocessOutcome

    @abstractmethod
    def terminate(self) -> None:
        pass

    @abstractmethod
    async def wait_for_exit(self, signal: Optional[Any] = None) -> bool:
        pass

    async def waitForExit(self, signal: Optional[Any] = None) -> bool:
        return await self.wait_for_exit(signal)


class SubprocessTerminalSpawnSpec:
    def __init__(
        self,
        argv: List[str],
        cwd: str,
        rows: int,
        cols: int,
        grace_ms: int,
        env: Optional[Dict[str, str]] = None,
        signal: Optional[Any] = None,
    ):
        self.argv = argv
        self.cwd = cwd
        self.rows = rows
        self.cols = cols
        self.graceMs = grace_ms
        self.env = env
        self.signal = signal


class SubprocessTerminalForeground:
    def __init__(self, process_group_id: int, input_waiting: bool):
        self.processGroupId = process_group_id
        self.inputWaiting = input_waiting


class SubprocessTerminalHandle(ABC):
    pid: int
    output: Any
    done: asyncio.Future

    @abstractmethod
    async def write(self, data: str) -> None:
        pass

    @abstractmethod
    async def inspect_foreground(self) -> Optional[SubprocessTerminalForeground]:
        pass

    @abstractmethod
    async def signal_foreground(self, signal: str) -> int:
        pass

    @abstractmethod
    async def terminate(self) -> None:
        pass
