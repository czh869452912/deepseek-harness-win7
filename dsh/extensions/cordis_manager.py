import json
from typing import Any, Dict, List, Optional
import yaml
from dsh.cordis.plugin import Plugin


class CordisManagerPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-cordis-manager`: Creative Mode (创造模式) plugin manager.
    Provides Cordis inspection, plugin lifecycle management, and preset authoring tools.
    """

    id = "cordis-manager"
    name = "@deepseek-ai/dsh-cordis-manager"
    inject = ["tools"]

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            return

        tools_service.register(
            name="cordis_list_plugins",
            description="List all active plugins loaded in the current Cordis context.",
            parameters={"type": "object", "properties": {}},
            handler=self.handle_list_plugins
        )

        tools_service.register(
            name="cordis_inspect_context",
            description="Inspect mounted Cordis services and system status.",
            parameters={"type": "object", "properties": {}},
            handler=self.handle_inspect_context
        )

        tools_service.register(
            name="cordis_unload_plugin",
            description="Unload an active plugin by its plugin ID.",
            parameters={
                "type": "object",
                "properties": {
                    "plugin_id": {"type": "string", "description": "ID of the plugin to unload"}
                },
                "required": ["plugin_id"]
            },
            handler=self.handle_unload_plugin
        )

        tools_service.register(
            name="cordis_dump_config",
            description="Dump active Cordis plugin composition configuration tree in YAML format.",
            parameters={"type": "object", "properties": {}},
            handler=self.handle_dump_config
        )

        ctx.on("agent/prompt-assemble", self.on_prompt_assemble)

    def on_prompt_assemble(self, prompt: str) -> str:
        cordis_prompt = (
            "\n\n[Creative Mode / Cordis Architecture Active]\n"
            "You are running in Creative Mode (创造模式) powered by Cordis 'Everything is a Plugin' architecture.\n"
            "You have access to `cordis_list_plugins`, `cordis_inspect_context`, `cordis_unload_plugin`, and `cordis_dump_config`.\n"
            "You can inspect active plugins, design new custom presets, and assist in extending the agent system.\n"
        )
        return prompt + cordis_prompt

    def handle_list_plugins(self, ctx: Optional[Any] = None) -> str:
        if not ctx:
            return "Error: Context unavailable"
        plugins = ctx.list_plugins()
        return json.dumps(plugins, indent=2, ensure_ascii=False)

    def handle_inspect_context(self, ctx: Optional[Any] = None) -> str:
        if not ctx:
            return "Error: Context unavailable"
        services = list(ctx._services.keys())
        plugins = [p["id"] for p in ctx.list_plugins()]
        info = {
            "services": services,
            "plugins": plugins
        }
        return json.dumps(info, indent=2, ensure_ascii=False)

    def handle_unload_plugin(self, plugin_id: str, ctx: Optional[Any] = None) -> str:
        if not ctx:
            return "Error: Context unavailable"
        success = ctx.unload_plugin(plugin_id)
        if success:
            return f"Plugin '{plugin_id}' successfully unloaded."
        return f"Plugin '{plugin_id}' not found or could not be unloaded."

    def handle_dump_config(self, ctx: Optional[Any] = None) -> str:
        if not ctx:
            return "Error: Context unavailable"
        plugins = ctx.list_plugins()
        dump_data = []
        for p in plugins:
            dump_data.append({
                "id": p["id"],
                "name": p["name"],
                "config": p["config"]
            })
        return yaml.dump(dump_data, allow_unicode=True)
