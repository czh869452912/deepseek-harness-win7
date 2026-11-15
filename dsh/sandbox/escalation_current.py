"""Current typed escalation decisions and localized approval display reasons."""
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.utils import _UNDEFINED,js_to_string
from dsh.cordis.json_text import stringify_json
from dsh.cordis.text import trim_js
from dsh.llm.error import HarnessError

WIDER_MODES={'read-only':['workspace-write','danger-full-access'],'workspace-write':['danger-full-access']}
ESCALATION_TARGETS=['workspace-write','danger-full-access']


class SandboxEscalationError(HarnessError):
    name='SandboxEscalationError'
    def __init__(self,message,code):super().__init__(message,code)


def invalid(message):return SandboxEscalationError(message,'SANDBOX_ESCALATION_INVALID_ARGUMENT')
def unavailable(message):return SandboxEscalationError(message,'SANDBOX_ESCALATION_UNAVAILABLE')


def validate_escalation_args(mode=_UNDEFINED,justification=_UNDEFINED):
    if mode is not _UNDEFINED and justification is _UNDEFINED:raise invalid('invalid escalation: sandbox_permissions requires a justification')
    if justification is not _UNDEFINED and mode is _UNDEFINED:raise invalid('invalid escalation: justification is only valid together with sandbox_permissions')
    if justification is not _UNDEFINED and not trim_js(justification):raise invalid('invalid justification: expected a non-empty sentence')


def display_reason(mode,justification):
    return dict(en='Allow this operation with '+mode+' permissions: '+justification,
        zh='允许本次操作使用 '+mode+' 权限：'+justification,
        ja=mode+' 権限でこの操作を許可します：'+justification,
        es='Permitir esta operación con permisos '+mode+': '+justification,
        fr='Autoriser cette opération avec les permissions '+mode+' : '+justification,
        de='Diesen Vorgang mit '+mode+'-Berechtigungen zulassen: '+justification,
        ru='Разрешить эту операцию с правами '+mode+': '+justification,
        pt='Permitir esta operação com permissões '+mode+': '+justification)


async def approve_escalation(request,approval):
    mode=request['requestedMode'];effective=request['effectiveMode'];justification=request['justification']
    if mode==effective:return effective
    if mode not in WIDER_MODES.get(effective,[]):raise invalid('sandbox escalation to "%s" is not strictly wider than this call\'s current "%s" mode' % (mode,effective))
    approver=approval.get('approver');agent=approval.get('agent')
    if approver is None:raise unavailable('sandbox escalation to "%s" requires approval, but no approval service is composed' % mode)
    if agent is None:raise unavailable('sandbox escalation to "%s" requires approval, but the call has no agent to route it through' % mode)
    ask=dict(agent=agent,toolName=approval['toolName'],callId=approval['callId'],reason='escalate sandbox to %s: %s' % (mode,justification),displayReason=display_reason(mode,justification))
    if approval.get('signal') is not None:ask['signal']=approval['signal']
    outcome=await await_callback_result(approver.request(ask))
    if outcome=='allowed-once':return mode
    if outcome=='rejected':raise SandboxEscalationError('the user rejected escalating this %s to "%s"; it stays denied, so stop and explain instead of working around it' % (request['subject'],mode),'SANDBOX_ESCALATION_REJECTED')
    if outcome=='cancelled':
        if approval.get('signal') is not None:approval['signal'].throwIfAborted()
        raise SandboxEscalationError('approval for escalating to "%s" was cancelled' % mode,'SANDBOX_ESCALATION_CANCELLED')
    if outcome=='unavailable':raise unavailable('sandbox escalation to "%s" requires approval, but no approval channel is available' % mode)
    raise RuntimeError('unreachable variant in EscalationOutcome: '+(js_to_string(outcome) if outcome is _UNDEFINED else stringify_json(outcome)))
