import os
import re
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.context.file_reference_local.grammar import active_at_token, format_file_mention
from dsh.context.file_reference_local.search import (
    DEFAULT_FILE_SEARCH_EXCLUDED_DIRECTORIES,
    DEFAULT_FILE_SEARCH_MAX_ENTRIES,
    DEFAULT_FILE_SEARCH_MAX_RESULTS,
    WorkspaceFileSearch,
)

FILE_REFERENCE_PROMPT = (
    "Paths prefixed with @ are files explicitly referenced by the user. "
    "Use the read tool when their contents are needed; "
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
        self.max_results = int(cfg.get("maxResults", DEFAULT_FILE_SEARCH_MAX_RESULTS))
        self.max_entries = int(cfg.get("maxEntries", DEFAULT_FILE_SEARCH_MAX_ENTRIES))
        self.excluded_directories = list(cfg.get("excludedDirectories", DEFAULT_FILE_SEARCH_EXCLUDED_DIRECTORIES))
        self.searcher: Optional[WorkspaceFileSearch] = None

    def apply(self, ctx: Any) -> None:
        cwd = ctx.get("fs").cwd if ctx.has("fs") and hasattr(ctx.get("fs"), "cwd") else os.getcwd()
        self.searcher = WorkspaceFileSearch(cwd, {
            "maxResults": self.max_results,
            "maxEntries": self.max_entries,
            "excludedDirectories": self.excluded_directories,
        })
        ctx.set_service("fileReferences", self.searcher)

        # Register system prompt section if system_prompt or systemPrompt is available
        sp = ctx.get("system_prompt") if ctx.has("system_prompt") else (ctx.get("systemPrompt") if ctx.has("systemPrompt") else None)
        if sp and hasattr(sp, "section"):
            sp.section("context:file-reference", FILE_REFERENCE_PROMPT, order=99)

        # Invalidate search index on tool result
        ctx.on("tools/result", lambda *a, **kw: self.searcher.invalidate() if self.searcher else None)

        # Hook agent/pre-step to expand file mentions if user explicitly typed @file
        async def hook_file_references(payload: Dict[str, Any]) -> Dict[str, Any]:
            messages = payload.get("messages", [])
            if not messages:
                return payload

            for msg in messages:
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    text = msg["content"]
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


__all__ = [
    "FileReferenceLocalPlugin",
    "WorkspaceFileSearch",
    "FILE_REFERENCE_PROMPT",
    "active_at_token",
    "format_file_mention",
    "DEFAULT_FILE_SEARCH_MAX_RESULTS",
    "DEFAULT_FILE_SEARCH_MAX_ENTRIES",
    "DEFAULT_FILE_SEARCH_EXCLUDED_DIRECTORIES",
]
