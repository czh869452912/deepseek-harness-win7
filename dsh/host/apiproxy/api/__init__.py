"""
ApiProxy API Domain Exports (`@deepseek-ai/dsh-apiproxy/api`).
Aligned 1:1 with reference `api/index.ts`.
"""

from dsh.host.apiproxy.api.rpc import ClientRequest, ServerResponse, ServerRequest
from dsh.host.apiproxy.api.rpc_map import OFFICIAL_RPC_METHODS
from dsh.host.apiproxy.api.agent_presets import AgentPresetsDomainHandler
from dsh.host.apiproxy.api.approvals import ApprovalsDomainHandler
from dsh.host.apiproxy.api.credentials import CredentialsDomainHandler
from dsh.host.apiproxy.api.downloads import DownloadsDomainHandler
from dsh.host.apiproxy.api.events import format_sse_frame
from dsh.host.apiproxy.api.goals import GoalsDomainHandler
from dsh.host.apiproxy.api.host import HostDomainHandler
from dsh.host.apiproxy.api.jobs import JobsDomainHandler
from dsh.host.apiproxy.api.llm import LLMDomainHandler
from dsh.host.apiproxy.api.questions import QuestionsDomainHandler
from dsh.host.apiproxy.api.session_search import SessionSearchDomainHandler
from dsh.host.apiproxy.api.sessions import SessionsDomainHandler
from dsh.host.apiproxy.api.settings import SettingsDomainHandler
from dsh.host.apiproxy.api.skills import SkillsDomainHandler
from dsh.host.apiproxy.api.subagents import SubagentsDomainHandler
from dsh.host.apiproxy.api.workspace import WorkspaceDomainHandler

__all__ = [
    "ClientRequest",
    "ServerResponse",
    "ServerRequest",
    "OFFICIAL_RPC_METHODS",
    "AgentPresetsDomainHandler",
    "ApprovalsDomainHandler",
    "CredentialsDomainHandler",
    "DownloadsDomainHandler",
    "format_sse_frame",
    "GoalsDomainHandler",
    "HostDomainHandler",
    "JobsDomainHandler",
    "LLMDomainHandler",
    "QuestionsDomainHandler",
    "SessionSearchDomainHandler",
    "SessionsDomainHandler",
    "SettingsDomainHandler",
    "SkillsDomainHandler",
    "SubagentsDomainHandler",
    "WorkspaceDomainHandler",
]
