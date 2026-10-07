import inspect
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from dsh.cordis.plugin import Plugin
from dsh.cordis.utils import _UNDEFINED
from dsh.fs.fs_local import FsError, FsTarget
from dsh.fs.tool_fs_sandbox import FsSandboxController


async def _fire_waterfall(ctx: Optional[Any], event_name: str, target: Any, actor: Any, default: Any = None) -> Any:
    """
    Dispatch one single-slot intent waterfall and return the decider's value.

    Matching the reference tool: the bare default is `undefined`, so a tree
    without a policy plugin keeps the provider's unconditional behaviour.
    """
    if not ctx or not hasattr(ctx, "waterfall"):
        return default
    return await ctx.waterfall(event_name, target, actor, lambda: default)


async def _observation_target(fs: Any, file_path: str, actor: Any = None, policy: Any = None) -> FsTarget:
    """
    The exact target the observation events and mutations share.

    One target identity per operation keeps the policy's observed-state key
    (`targetKey`) consistent between the read that records it and the write
    or edit that guards against it.
    """
    agent = getattr(actor, 'agent', None)
    header = getattr(getattr(agent, 'session', None), 'header', None)
    cwd = header.get('cwd') if isinstance(header, dict) else getattr(header, 'cwd', None)
    if policy and policy.get('workspaceRoot'):
        cwd = policy['workspaceRoot']
    elif cwd and (re.search(r'(?:^|[\\/])\.\.(?:[\\/]|$)', cwd) or
                  re.search(r'(?:^|[\\/])\.\.(?:[\\/]|$)', file_path)):
        cwd = os.path.realpath(cwd)
    if hasattr(fs, 'resolve'):
        options = {'signal': getattr(actor, 'signal', None)}
        if cwd is not None:
            options['cwd'] = cwd
        target = fs.resolve(file_path, options)
        return await target if inspect.isawaitable(target) else target
    resolved_path = fs.resolve_path(file_path) if hasattr(fs, "resolve_path") else file_path
    return FsTarget(target_key=resolved_path, display_path=resolved_path)


async def _mutation_policy(ctx: Any, fs: Any, actor: Any) -> Any:
    if getattr(fs, 'sandboxMode', None) is None:
        return None
    policy = ctx.get('sandboxPolicy')
    if policy is None:
        raise RuntimeError('tool-fs: confining filesystem requires sandboxPolicy')
    agent = getattr(actor, 'agent', None)
    value = policy.resolve({'session': agent.session} if agent is not None else {})
    return await value if inspect.isawaitable(value) else value


def _emit_observed(ctx: Optional[Any], target: FsTarget, observation: Dict[str, Any], actor: Any) -> None:
    """Record one authoritative presence/absence observation for the actor."""
    if ctx and hasattr(ctx, "emit"):
        ctx.emit("fs/observed", target, observation, actor)


def format_read_output(display_path: str, offset: int, lines: List[Tuple[int, str]], total_lines: int, truncated_by_bytes: bool = False) -> str:
    rendered_lines = [
        f"{str(num).rjust(6, ' ')}  {text}"
        for num, text in lines
    ]
    body = "\n".join(rendered_lines)
    trunc_notice = "\n[output truncated by byte limit]" if truncated_by_bytes else ""
    return (
        f"<path>{display_path}</path>\n"
        f"<type>file</type>\n"
        f"<content>\n"
        f"{body}{trunc_notice}\n"
        f"</content>"
    )


def format_write_output(display_path: str, operation: str) -> str:
    verb = "Created" if operation == "create" else "Updated"
    return (
        f"<path>{display_path}</path>\n"
        f"<type>file</type>\n"
        f"<content>\n"
        f"{verb} file\n"
        f"</content>"
    )


def format_edit_output(display_path: str, replace_all: bool) -> str:
    if replace_all:
        return f"The file {display_path} has been updated. All occurrences were successfully replaced."
    return f"The file {display_path} has been updated successfully."


class ToolFsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-fs`: Model-facing read, write, and edit tools over ctx.fs.
    """

    id = "tool-fs"
    name = "@deepseek-ai/dsh-tool-fs"
    inject = ["tools", "fs", "systemPrompt"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.read_limit = cfg.get("readLimit", 2000)
        self.read_max_line_length = cfg.get("readMaxLineLength", 2000)
        self.read_max_bytes = cfg.get("readMaxBytes", 50 * 1024)
        self.read_stream_min_size = cfg.get("readStreamMinSize", 10 * 1024 * 1024)

    def apply(self, ctx: Any) -> None:
        from dsh.fs.tool_read_render import _integer
        for name, value in (('readLimit', self.read_limit), ('readMaxLineLength', self.read_max_line_length),
                ('readMaxBytes', self.read_max_bytes), ('readStreamMinSize', self.read_stream_min_size)):
            if not _integer(value, 1):
                raise ValueError('tool-fs: %s must be a positive integer' % name)
        from dsh.fs.tool_read_image import apply_read_image_tool
        ctx.inject(['attachments'], apply_read_image_tool)
        tools = ctx.get("tools")
        if not tools:
            return

        from dsh.fs.tool_read import apply_read_tool
        from dsh.fs.tool_fs_mutation import apply_mutation_tool
        apply_read_tool(ctx, dict(limit=self.read_limit, maxLineLength=self.read_max_line_length,
            maxBytes=self.read_max_bytes, streamMinSize=self.read_stream_min_size))
        sandbox = FsSandboxController(ctx)
        apply_mutation_tool(ctx, sandbox, 'write')
        apply_mutation_tool(ctx, sandbox, 'edit')


__all__ = ["ToolFsPlugin", "format_read_output", "format_write_output", "format_edit_output"]
