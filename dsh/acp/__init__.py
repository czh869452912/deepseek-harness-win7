"""
Agent Communication Protocol (ACP) package matching reference/packages/acp/acp
"""
from dsh.acp.codec import turn_end_to_stop_reason
from dsh.acp.content import AcpContentError, admit_acp_prompt, assistant_block_to_acp, supports_acp_image_prompts
from dsh.acp.server import AcpPlugin, SessionRecord

name = "acp"
inject = ["agents"]

__all__ = [
    "AcpPlugin",
    "SessionRecord",
    "turn_end_to_stop_reason",
    "AcpContentError",
    "admit_acp_prompt",
    "assistant_block_to_acp",
    "supports_acp_image_prompts",
    "name",
    "inject",
]
