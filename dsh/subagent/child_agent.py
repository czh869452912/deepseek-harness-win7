"""Fresh and restored child composition and delegation policy snapshots."""
from dsh.subagent.composition import child_options, parent_options, DELEGATION_CONTEXT
from dsh.subagent.composition_current import resolve_depth
from dsh.subagent.errors import SubagentError


def child_session_meta(parent, depth, is_seeded, selected_preset=None):
    header = parent.session.header
    presets = parent.ctx.get('agentPresets')
    preset = selected_preset if selected_preset is not None else presets.composedPreset(parent.ctx) if presets is not None else None
    result = dict(parentSession=header['id'],isSeeded=is_seeded,origin='subagent',delegationDepth=depth)
    if header.get('cwd') is not None:
        result['cwd'] = header['cwd']
    if preset is not None:
        result['agentPreset'] = preset
    return result


def capture_delegated_policy_overrides(parent):
    presets, sandbox = parent.ctx.get('permissionPresets'),parent.ctx.get('sandboxPolicy')
    preset = presets.current(parent.session) if presets is not None else None
    result = {}
    if preset in ('auto','danger-full-access'):
        result['permissionPreset'] = preset
    if sandbox is not None:
        mode = sandbox.overrideOf(parent.session)
        if mode is not None:
            result['sandboxMode'] = mode
    if parent.ctx.get('approval') is not None:
        result['approvalPolicy'] = 'never'
    return result


def append_delegated_policy_overrides(session, overrides):
    if 'sandboxMode' in overrides:
        session.append('sandbox/mode',dict(mode=overrides['sandboxMode'],source='delegation'))
    if 'approvalPolicy' in overrides:
        session.append('approval/policy',dict(policy=overrides['approvalPolicy'],source='delegation'))
    if 'permissionPreset' in overrides:
        session.append('permission/preset',dict(preset=overrides['permissionPreset']))


def apply_child_overrides(child_ctx, composition):
    prompt = child_ctx.get('systemPrompt')
    prompt.context(dict(name='subagent:delegation',order=prompt.getContextOrder('SUBAGENT_DELEGATION'),text=DELEGATION_CONTEXT))
    if composition.get('persona') is not None:
        prompt.section(dict(name='deployment:persona-prefix',order=prompt.getSectionOrder('DEPLOYMENT_PERSONA_PREFIX'),text=composition['persona']))
    if composition.get('toolFilter') is not None:
        child_ctx.get('tools').restrict(composition['toolFilter'])


def apply_child_composition(child_ctx, parent, composition):
    presets = child_ctx.get('agentPresets')
    if composition.get('agentPreset') is not None:
        if presets is None:
            raise SubagentError('selecting a child agent preset requires the agent-presets service','PRESET_UNAVAILABLE')
        async def mount():
            await presets.mount(child_ctx,composition['agentPreset'])
            apply_child_overrides(child_ctx,composition)
        return mount()
    if parent is not None and presets is not None:
        presets.composeFrom(child_ctx,parent.ctx)
    apply_child_overrides(child_ctx,composition)


resolveChildDepth = resolve_depth
resolveChildAgentOptions = child_options
parentAgentOptionsForDelegation = parent_options
childSessionMeta = child_session_meta
captureDelegatedPolicyOverrides = capture_delegated_policy_overrides
appendDelegatedPolicyOverrides = append_delegated_policy_overrides
applyChildComposition = apply_child_composition
