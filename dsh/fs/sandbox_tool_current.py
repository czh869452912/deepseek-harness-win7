"""Current filesystem one-call policy and escalation choreography."""
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.text import trim_js
from dsh.cordis.utils import _UNDEFINED
from dsh.core.tools import ToolArgsError
from dsh.sandbox.escalation_current import validate_escalation_args, approve_escalation
from .tool_fs_sandbox import FsSandboxController


class CurrentFsSandboxController(FsSandboxController):
    def schema_fields(self):
        return dict(sandbox_permissions=dict(type='string', enum=list(self.escalation_modes),
            description='The narrowest wider sandbox mode for a one-shot retry of the exact operation the sandbox just denied; the retry asks the user for approval.'),
            justification=dict(type='string', description='Required with sandbox_permissions: one sentence for the user explaining why this exact file operation needs the wider access. Use the language of the user’s current request.'))

    async def resolve_policy(self, tool_name, arguments, execution):
        agent = getattr(execution, 'agent', None)
        policy = await await_callback_result(self.policy.resolve(dict(session=agent.session) if agent is not None else {})) if self.policy is not None else None
        mode = arguments.get('sandbox_permissions', _UNDEFINED)
        justification = arguments.get('justification', _UNDEFINED)
        if mode is not _UNDEFINED and mode == (policy or {}).get('mode', _UNDEFINED): return policy
        normalized = _UNDEFINED if mode is _UNDEFINED and isinstance(justification, str) and not trim_js(justification) else justification
        validate_escalation_args(mode, normalized)
        if mode is _UNDEFINED or justification is _UNDEFINED: return policy
        if not self.escalation_modes:
            raise ToolArgsError(tool_name, ['sandbox_permissions is not available in this composition (no sandboxing filesystem to escalate)'])
        approved = await approve_escalation(dict(requestedMode=mode, justification=justification, effectiveMode=policy['mode'], subject='operation'),
            dict(approver=self.ctx.get('approval'), agent=agent, callId=getattr(execution, 'callId', None), toolName=tool_name, signal=execution.signal))
        return dict(policy, mode=approved)
