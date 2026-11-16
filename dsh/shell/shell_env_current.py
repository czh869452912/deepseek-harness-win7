"""Current shell environment registry without the retired JSONL contributor."""
from dsh.cordis.schema import Schema
from .shell_env import ShellEnvPlugin,ShellEnvRegistry


class CurrentShellEnvPlugin(ShellEnvPlugin):
    Config=Schema.object(dict(dshHome=Schema.string()))

    def apply(self,ctx):ShellEnvRegistry(ctx,self.config)
