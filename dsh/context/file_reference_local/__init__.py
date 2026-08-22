import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin
from dsh.context.file_reference_local.search import WorkspaceFileSearch

FILE_REFERENCE_PROMPT = (
    "Paths prefixed with @ are files explicitly referenced by the user. "
    "Use the str_replace_editor view command or file tools when their contents are needed; "
    "do not claim to have inspected a file before reading it."
)


class FileReferenceLocalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-file-reference-local`: Resolves `@filename` references
    in user prompts and injects file reference guidance into system prompt.
    """

    id = "file-reference-local"
    name = "@deepseek-ai/dsh-file-reference-local"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.max_inline_bytes = int(cfg.get("maxInlineBytes", 16384))
        self.max_results = int(cfg.get("maxResults", 8))
        self.searcher: Optional[WorkspaceFileSearch] = None

    def apply(self, ctx: Any) -> None:
        cwd = ctx.get("fs").cwd if ctx.has("fs") and hasattr(ctx.get("fs"), "cwd") else os.getcwd()
        self.searcher = WorkspaceFileSearch(cwd, {"maxResults": self.max_results})
        ctx.set_service("fileReferences", self.searcher)

        # 1. Register system prompt section if systemPrompt is available
        if ctx.has("system_prompt"):
            sp = ctx.get("system_prompt")
            if hasattr(sp, "section"):
                sp.section("context:file-reference", FILE_REFERENCE_PROMPT, order=99)

        # 2. Invalidate search index on tool result
        ctx.on("tools/result", lambda *a, **kw: self.searcher.invalidate() if self.searcher else None)

        # 3. Hook agent/pre-step to expand file mentions if user explicitly typed @file
        async def hook_file_references(payload: Dict[str, Any]) -> Dict[str, Any]:
            messages = payload.get("messages", [])
            if not messages:
                return payload

            for msg in messages:
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    text = msg["content"]
                    # Match @filename or @"path with spaces"
                    matches = re.findall(r'@(?:\"([^\"]+)\"|([a-zA-Z0-9_\-\.\/\\]+))', text)
                    if matches:
                        inlined_snippets = []
                        for m_quoted, m_plain in matches:
                            rel_path = m_quoted or m_plain
                            if not rel_path or rel_path.startswith("deepseek-ai"):
                                continue
                            abs_path = os.path.normpath(os.path.join(cwd, rel_path))
                            if os.path.isfile(abs_path):
                                try:
                                    size = os.path.getsize(abs_path)
                                    if size <= self.max_inline_bytes:
                                        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                                            snippet = f.read()
                                        inlined_snippets.append(f"[@{rel_path} content]:\n```\n{snippet}\n```")
                                    else:
                                        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                                            snippet = f.read(self.max_inline_bytes)
                                        inlined_snippets.append(
                                            f"[@{rel_path} content (first {self.max_inline_bytes} bytes)]:\n```\n{snippet}\n```\n(File exceeds max inline size)"
                                        )
                                except Exception:
                                    pass

                        if inlined_snippets:
                            msg["content"] = text + "\n\n" + "\n\n".join(inlined_snippets)

            return payload

        ctx.on("agent/pre-step", hook_file_references)
