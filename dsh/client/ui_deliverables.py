"""
Deliverables plugin, node half.

Port of reference/packages/client/ui-deliverables/src/index.ts: it registers the
response-format guidance that lets the browser half recognize final-response
file references.
"""

from typing import Any

from dsh.core.system_prompt.types import FIRST_PARTY_SECTION_ORDER
from dsh.cordis.plugin import Plugin

# Stable final-response guidance owned by the matching renderer.
FILE_REFERENCE_PROMPT = (
    "When you successfully create or modify files, mention the primary outputs in your final response. "
    "To make those and any other changed-file references clickable in Web, format them as Markdown inline code "
    "using the exact file-tool path, or a basename when unique among the files changed in that turn."
)


class ClientUiDeliverablesPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-client-ui-deliverables`: registers model guidance
    for the file-reference renderer shipped by this package.
    """

    id = "@deepseek-ai/dsh-client-ui-deliverables"
    name = "@deepseek-ai/dsh-client-ui-deliverables"
    inject = ["systemPrompt"]

    def apply(self, ctx: Any) -> None:
        ctx.systemPrompt.section(
            {
                "name": "ui:deliverable-file-references",
                "order": FIRST_PARTY_SECTION_ORDER.DELIVERABLE_FILE_REFERENCES,
                "text": FILE_REFERENCE_PROMPT,
            }
        )
