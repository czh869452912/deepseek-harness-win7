"""
Subprocess service definition and environment scrub.
1:1 parity with @deepseek-ai/dsh-subprocess package.
Python 3.8.10 compatible.
"""

from abc import ABC, abstractmethod
import os
import re
from typing import Any, Dict, Optional

from dsh.cordis.service import Service
from dsh.subprocess.types import (
    DSH_ENV_PREFIX,
    SubprocessHandle,
    SubprocessSpawnSpec,
    SubprocessTerminalHandle,
    SubprocessTerminalSpawnSpec,
)

SENSITIVE_ENV_PATTERN = re.compile(r"KEY|PASSWORD|SECRET|TOKEN", re.IGNORECASE)


def scrubbed_parent_env() -> Dict[str, str]:
    """
    Return the ambient parent environment minus credential-shaped names
    and minus all DSH_* names.
    """
    env: Dict[str, str] = {}
    for key, value in os.environ.items():
        if value is not None:
            if SENSITIVE_ENV_PATTERN.search(key):
                continue
            if key.upper().startswith(DSH_ENV_PREFIX):
                continue
            env[key] = value
    return env


class SubprocessRuntime(Service, ABC):
    """Abstract subprocess service (`ctx.subprocess`)."""

    def __init__(self, ctx: Any):
        super().__init__(ctx, "subprocess")

    @abstractmethod
    async def resolve_executable(
        self,
        command: str,
        env: Optional[Dict[str, str]] = None,
        signal: Optional[Any] = None,
    ) -> str:
        pass

    @abstractmethod
    def spawn(self, spec: SubprocessSpawnSpec) -> SubprocessHandle:
        pass

    @abstractmethod
    async def spawn_terminal(self, spec: SubprocessTerminalSpawnSpec) -> SubprocessTerminalHandle:
        pass
