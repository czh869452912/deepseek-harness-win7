from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.utils import _UNDEFINED


WIDER_MODES = {'read-only': ['workspace-write', 'danger-full-access'], 'workspace-write': ['danger-full-access']}
ESCALATION_TARGETS = ['workspace-write', 'danger-full-access']


def validate_escalation_args(mode, justification):
    if mode is not _UNDEFINED and justification is _UNDEFINED:
        raise ValueError('invalid escalation: sandbox_permissions requires a justification')
    if justification is not _UNDEFINED and mode is _UNDEFINED:
        raise ValueError('invalid escalation: justification is only valid together with sandbox_permissions')
    if justification is not _UNDEFINED and not justification.strip():
        raise ValueError('invalid justification: expected a non-empty sentence')


def sandbox_denial_marker(mode):
    return '[sandbox: file access denied under %s mode]' % mode


def escalation_hint_marker(subject):
    return '[sandbox: escalation available — retry this exact %s once with sandbox_permissions (the narrowest wider mode that suffices) + justification; the approval prompt asks the user]' % subject


async def approve_escalation(request, approval):
    mode, effective = request['requestedMode'], request['effectiveMode']
    if mode not in WIDER_MODES.get(effective, []):
        raise ValueError('sandbox escalation to "%s" is not strictly wider than this call\'s current "%s" mode' % (mode, effective))
    approver, agent = approval.get('approver'), approval.get('agent')
    if approver is None:
        raise ValueError('sandbox escalation to "%s" requires approval, but no approval service is composed' % mode)
    if agent is None:
        raise ValueError('sandbox escalation to "%s" requires approval, but the call has no agent to route it through' % mode)
    ask = dict(agent=agent, toolName=approval['toolName'], callId=approval['callId'],
        reason='escalate sandbox to %s: %s' % (mode, request['justification']))
    if approval.get('signal') is not None:
        ask['signal'] = approval['signal']
    outcome = await await_callback_result(approver.request(ask))
    if outcome == 'allowed-once':
        return mode
    if outcome == 'rejected':
        raise ValueError('the user rejected escalating this %s to "%s"' % (request['subject'], mode))
    if outcome == 'cancelled':
        raise ValueError('approval for escalating to "%s" was cancelled' % mode)
    if outcome == 'unavailable':
        raise ValueError('sandbox escalation to "%s" requires approval, but no approval channel is available' % mode)
    raise ValueError('unexpected EscalationOutcome: %s' % outcome)
