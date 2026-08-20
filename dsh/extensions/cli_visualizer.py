import sys
import json
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


class CliVisualizerPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-cli-visualizer`: Displays live execution process visualization in CLI.
    Listens to turn, step, tool execution waterfall, and agent events.
    """

    id = "cli-visualizer"
    name = "@deepseek-ai/dsh-cli-visualizer"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.verbose = self.config.get("verbose", True)
        self.show_tools = self.config.get("showTools", True)

    def apply(self, ctx: Any) -> None:
        if not self.verbose:
            return

        ctx.on("turn/start", self.on_turn_start)
        ctx.on("step/start", self.on_step_start)
        ctx.on("tools/pre-execute", self.on_tool_pre_execute)
        ctx.on("tools/post-execute", self.on_tool_post_execute)
        ctx.on("turn/end", self.on_turn_end)

    def on_turn_start(self, user_input: str) -> None:
        sys.stdout.write(f"\n🚀 [Turn Started] Processing input...\n")
        sys.stdout.flush()

    def on_step_start(self, step_num: int) -> None:
        sys.stdout.write(f"\n🔹 [Step {step_num}]\n")
        sys.stdout.flush()

    def on_tool_pre_execute(self, payload: Dict[str, Any], next_fn: Any = None) -> Dict[str, Any]:
        if self.show_tools:
            name = payload.get("name", "unknown")
            args = payload.get("arguments", {})
            args_str = json.dumps(args, ensure_ascii=False)
            if len(args_str) > 120:
                args_str = args_str[:117] + "..."
            sys.stdout.write(f"   🔧 [Executing Tool] {name}({args_str})\n")
            sys.stdout.flush()
        return payload

    def on_tool_post_execute(self, payload: Dict[str, Any], next_fn: Any = None) -> Dict[str, Any]:
        if self.show_tools:
            name = payload.get("name", "unknown")
            err = payload.get("error")
            res = payload.get("result")
            if err:
                sys.stdout.write(f"   ❌ [Tool Error] {name}: {err}\n")
            else:
                res_preview = str(res).replace('\n', ' ')
                if len(res_preview) > 100:
                    res_preview = res_preview[:97] + "..."
                sys.stdout.write(f"   ✅ [Tool Done] {name} -> {res_preview}\n")
            sys.stdout.flush()
        return payload

    def on_turn_end(self, final_response: str) -> None:
        sys.stdout.write(f"\n🏁 [Turn Complete]\n")
        sys.stdout.flush()
