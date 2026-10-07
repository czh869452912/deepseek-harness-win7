import inspect

from dsh.cordis.utils import _UNDEFINED
from dsh.fs.fs_local import FsError
from dsh.sandbox.escalation import (
    ESCALATION_TARGETS, approve_escalation, escalation_hint_marker,
    sandbox_denial_marker, validate_escalation_args,
)


class FsSandboxController:
    def __init__(self, ctx):
        self.ctx = ctx
        confined = getattr(ctx.get('fs'), 'sandboxMode', None) is not None
        self.escalation_modes = list(ESCALATION_TARGETS) if confined else []
        self.policy = ctx.get('sandboxPolicy') if confined else None
        if confined and self.policy is None:
            raise ValueError('tool-fs: the mounted filesystem confines but ctx.sandboxPolicy is missing')

    def schema_fields(self):
        return dict(sandbox_permissions=dict(type='string', enum=list(self.escalation_modes),
            description='The wider sandbox mode this file operation needs. Only valid as a one-shot retry of an operation the sandbox just denied; requires justification and user approval.'),
            justification=dict(type='string', description='Required with sandbox_permissions: one sentence for the user explaining why this exact file operation needs the wider access.'))

    async def resolve_policy(self, tool_name, arguments, execution):
        mode = arguments.get('sandbox_permissions', _UNDEFINED)
        justification = arguments.get('justification', _UNDEFINED)
        validate_escalation_args(mode, justification)
        agent = getattr(execution, 'agent', None)
        policy = self.policy.resolve(dict(session=agent.session) if agent is not None else {}) if self.policy is not None else None
        if inspect.isawaitable(policy):
            policy = await policy
        if mode is _UNDEFINED or justification is _UNDEFINED:
            return policy
        if not self.escalation_modes:
            raise ValueError('sandbox_permissions is not available in this composition (no sandboxing filesystem to escalate)')
        approved = await approve_escalation(dict(requestedMode=mode, justification=justification,
            effectiveMode=policy['mode'], subject='operation'), dict(approver=self.ctx.get('approval'), agent=agent,
            callId=getattr(execution, 'callId', None), toolName=tool_name, signal=getattr(execution, 'signal', None)))
        return dict(policy, mode=approved)

    def map_error(self, error, policy):
        if not isinstance(error, FsError) or error.code != 'FS_SANDBOX_DENIED':
            return error
        return FsError(sandbox_denial_marker(policy['mode']) + '\n' + escalation_hint_marker('operation'),
            'FS_SANDBOX_DENIED', cause=error)
