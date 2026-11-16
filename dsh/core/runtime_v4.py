"""Explicit v4 installation mounts for the fixed rc.3 candidate.

Earlier current adapters retain their historical default for isolated consumers;
the coordinated candidate graph selects its session format at these roots.
"""
from dsh.cordis.plugin import Plugin
from dsh.core.session.current_session import CurrentSessionStore
from dsh.core.agent_current import CurrentAgentPlugin
from dsh.session.projections import SessionProjectionRegistry


class SessionV4Plugin(Plugin):
    id='session';name='@deepseek-ai/dsh-session'

    def apply(self,ctx):CurrentSessionStore(ctx,4)


class SessionProjectionsV4Plugin(Plugin):
    id='session-projection';name='@deepseek-ai/dsh-session-projection'

    def apply(self,ctx):SessionProjectionRegistry(ctx,4)


class AgentV4Plugin(CurrentAgentPlugin):
    inject=['sessionProjections']
