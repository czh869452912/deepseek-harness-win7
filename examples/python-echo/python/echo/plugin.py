from dsh.plugin_api import Plugin
from .formatting import format_echo


class EchoPlugin(Plugin):
    name = "python-echo"
    inject = ["tools"]

    def apply(self, ctx, config):
        async def execute(args, execution):
            return format_echo(args["text"])

        ctx.get("tools").register({
            "name": "python_echo",
            "description": "Echo a string through a Python plugin.",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            "execute": execute,
            "output": {"schema": {"type": "string"},
                       "render": lambda args, value: [{"type": "text", "text": value}]},
        })
