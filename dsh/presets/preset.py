"""
Agent-preset vocabulary shared by discovery, mounting, and consumers.
1:1 with reference @deepseek-ai/dsh-agent-presets/preset.ts.
Python 3.8.10 compatible.
"""

import re
from typing import Any, Dict, List, Optional, Union


# Ids a preset directory may use.
PRESET_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class AgentPreset:
    """One preset directory that carries a mountable agent composition."""

    def __init__(
        self,
        id: str,
        trust: str,
        path: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        order: Optional[float] = None,
        broken: Optional[str] = None,
    ):
        self.id = id
        self.trust = trust  # 'system' | 'user'
        self.path = path
        self.name = name
        self.description = description
        self.order = order
        self.broken = broken

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "id": self.id,
            "trust": self.trust,
            "path": self.path,
        }
        if self.name is not None:
            res["name"] = self.name
        if self.description is not None:
            res["description"] = self.description
        if self.order is not None:
            res["order"] = self.order
        if self.broken is not None:
            res["broken"] = self.broken
        return res


class PresetRoot:
    """One directory scanned for preset subdirectories."""

    def __init__(self, path: str, trust: str = "user"):
        self.path = path
        self.trust = trust  # 'system' | 'user'


class Config:
    """Plugin config: which preset is the default, and where presets live."""

    def __init__(
        self,
        default: str = "standard",
        roots: Optional[List[PresetRoot]] = None,
        include_user_root: bool = True,
    ):
        self.default = default
        self.roots = roots if roots is not None else []
        self.include_user_root = include_user_root


class UnknownPresetError(ValueError):
    """No configured root supplies the requested preset."""

    def __init__(self, preset_id: str, available: List[str]):
        avail_str = ", ".join(available) if available else "none"
        super().__init__(
            f'agent-presets: preset "{preset_id}" not found (available: {avail_str})'
        )
        self.preset_id = preset_id
        self.available = available


class PresetMountError(RuntimeError):
    """A preset exists but its composition cannot be installed."""

    def __init__(self, preset_id: str, reason: str, cause: Optional[Exception] = None):
        super().__init__(f'agent-presets: preset "{preset_id}" failed to mount: {reason}')
        self.preset_id = preset_id
        self.reason = reason
        self.__cause__ = cause


class InvalidPresetIdError(ValueError):
    """A preset id that cannot be used as a directory name under a root."""

    def __init__(self, preset_id: str):
        super().__init__(
            f"agent-presets: preset id {repr(preset_id)} must match ^[a-z0-9][a-z0-9-]*$ — "
            "the id is a directory name, so anything else could escape the preset root"
        )
        self.preset_id = preset_id


class PresetExistsError(ValueError):
    """A copy target that is already occupied — a copy never overwrites."""

    def __init__(self, preset_id: str):
        super().__init__(
            f'agent-presets: preset "{preset_id}" already exists — '
            "a copy never overwrites; delete the existing preset first or choose another id"
        )
        self.preset_id = preset_id


class PresetNotWritableError(PermissionError):
    """Authoring was attempted where the deployment allows none."""

    def __init__(self, preset_id: str, reason: str):
        super().__init__(f'agent-presets: preset "{preset_id}" cannot be written: {reason}')
        self.preset_id = preset_id
        self.reason = reason
