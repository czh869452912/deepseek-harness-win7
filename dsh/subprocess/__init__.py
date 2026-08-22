"""
Subprocess service definition and local provider.
1:1 parity with @deepseek-ai/dsh-subprocess package.
Python 3.8.10 compatible.
"""

from dsh.subprocess.collector import OutputCollector
from dsh.subprocess.local import child_env, LocalSubprocessHandle, LocalSubprocessRuntime, LocalTerminalHandle
from dsh.subprocess.service import SENSITIVE_ENV_PATTERN, SubprocessRuntime, scrubbed_parent_env
from dsh.subprocess.types import (
    CollectedOutput,
    DSH_ENV_PREFIX,
    SubprocessCollect,
    SubprocessCollectedOutputs,
    SubprocessHandle,
    SubprocessOutcome,
    SubprocessOutputMode,
    SubprocessOutputRead,
    SubprocessOutputReader,
    SubprocessSpawnSpec,
    SubprocessStdinMode,
    SubprocessStdio,
    SubprocessTerminalForeground,
    SubprocessTerminalHandle,
    SubprocessTerminalSpawnSpec,
)

__all__ = [
    "DSH_ENV_PREFIX",
    "SENSITIVE_ENV_PATTERN",
    "scrubbed_parent_env",
    "child_env",
    "SubprocessRuntime",
    "LocalSubprocessRuntime",
    "LocalSubprocessHandle",
    "LocalTerminalHandle",
    "OutputCollector",
    "CollectedOutput",
    "SubprocessCollect",
    "SubprocessCollectedOutputs",
    "SubprocessHandle",
    "SubprocessOutcome",
    "SubprocessOutputMode",
    "SubprocessOutputRead",
    "SubprocessOutputReader",
    "SubprocessSpawnSpec",
    "SubprocessStdinMode",
    "SubprocessStdio",
    "SubprocessTerminalForeground",
    "SubprocessTerminalHandle",
    "SubprocessTerminalSpawnSpec",
]
