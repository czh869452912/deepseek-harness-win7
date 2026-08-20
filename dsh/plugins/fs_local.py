from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.services.fs import FsService


class FsLocalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-fs-local`: Mounts local filesystem service (`ctx.fs`).
    """

    id = "fs-local"
    name = "@deepseek-ai/dsh-fs-local"

    def apply(self, ctx: Any) -> None:
        cwd = self.config.get("cwd")
        fs_service = FsService(cwd=cwd)
        ctx.set_service("fs", fs_service)
