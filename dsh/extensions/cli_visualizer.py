import sys
import json
import inspect
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


def _safe_write(text: str) -> None:
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (UnicodeEncodeError, AttributeError):
        try:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            encoded = text.encode(enc, errors="replace").decode(enc, errors="replace")
            sys.stdout.write(encoded)
            sys.stdout.flush()
        except Exception:
            pass


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
        _safe_write(f"\n🚀 [Turn Started] Processing input...\n")

    def on_step_start(self, step_num: int) -> None:
        _safe_write(f"\n🔹 [Step {step_num}]\n")

    async def on_tool_pre_execute(self, payload: Dict[str, Any], next_fn: Any = None) -> Dict[str, Any]:
        if self.show_tools:
            name = payload.get("name", "unknown")
            args = payload.get("arguments", {})
            args_str = json.dumps(args, ensure_ascii=False)
            if len(args_str) > 120:
                args_str = args_str[:117] + "..."
            _safe_write(f"   🔧 [Executing Tool] {name}({args_str})\n")
        # Waterfall listeners must delegate to the next stage.  Keeping a
        # payload fallback makes direct/unit invocation backwards compatible.
        if callable(next_fn):
            result = next_fn()
            if inspect.isawaitable(result):
                result = await result
            return result
        return payload

    async def on_tool_post_execute(self, payload: Dict[str, Any], next_fn: Any = None) -> Dict[str, Any]:
        if self.show_tools:
            name = payload.get("name", "unknown")
            err = payload.get("error")
            res = payload.get("result")
            if err:
                _safe_write(f"   ❌ [Tool Error] {name}: {err}\n")
            else:
                res_preview = str(res).replace('\n', ' ')
                if len(res_preview) > 100:
                    res_preview = res_preview[:97] + "..."
                _safe_write(f"   ✅ [Tool Done] {name} -> {res_preview}\n")
        if callable(next_fn):
            result = next_fn()
            if inspect.isawaitable(result):
                result = await result
            return result
        return payload

    def on_turn_end(self, final_response: str) -> None:
        _safe_write(f"\n🏁 [Turn Complete]\n")
