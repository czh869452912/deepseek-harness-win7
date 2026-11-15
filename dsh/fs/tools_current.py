"""Current file tools; the coordinated profile switch selects these providers."""
from dsh.fs.tool_fs import ToolFsPlugin
from dsh.fs.tool_fs_search import ToolFsSearchPlugin


class CurrentToolFs(ToolFsPlugin):
    current_contract = True


class CurrentToolFsSearch(ToolFsSearchPlugin):
    current_contract = True


class CurrentPatchToolFs(CurrentToolFs):
    """Current configurable suite including optional guarded batch patching."""
    inject = CurrentToolFs.inject + ['workingDirectory']
    directory_aware = True

    def apply(self, ctx):
        from .tool_read_render import _integer
        from .tool_read import apply_read_tool
        from .read_image_current import apply_read_image_tool
        from .tool_fs_mutation import apply_mutation_tool
        from .sandbox_tool_current import CurrentFsSandboxController
        from .apply_patch_tool import apply_patch_tool
        for name, value in [('readLimit', self.read_limit), ('readMaxLineLength', self.read_max_line_length),
                            ('readMaxBytes', self.read_max_bytes), ('readStreamMinSize', self.read_stream_min_size)]:
            if not _integer(value, 1): raise ValueError('tool-fs: %s must be a positive integer' % name)
        config = self.config
        if config.get('read', True):
            apply_read_tool(ctx, dict(limit=self.read_limit, maxLineLength=self.read_max_line_length,
                maxBytes=self.read_max_bytes, streamMinSize=self.read_stream_min_size), current=True, directory_aware=True, latest=True)
        if config.get('readImage', True):
            ctx.inject(['attachments'], apply_read_image_tool)
        if config.get('write', True) or config.get('edit', True) or config.get('applyPatch', False):
            sandbox = CurrentFsSandboxController(ctx)
            for name in ('write', 'edit'):
                if config.get(name, True): apply_mutation_tool(ctx, sandbox, name, current=True, directory_aware=True, latest=True)
            if config.get('applyPatch', False): apply_patch_tool(ctx, sandbox)
