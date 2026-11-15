"""
Agent-scoped model selection shared by runtime entry points.
Aligned 1:1 with official `@deepseek-ai/dsh-agent/model-selection`.
"""

import inspect

from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.context import Context
from dsh.cordis.service import Service
from dsh.cordis.schema import Schema as z
from dsh.settings.provider import install_settings_section
from dsh.settings.types import settings_namespace
from dsh.core.session.json import UNDEFINED


def _selection(provider, model, effort=UNDEFINED):
    result = dict(provider=provider, model=model)
    if effort is not UNDEFINED:
        result['reasoningEffort'] = effort
    return result


def _same_selection(left, right):
    return left is right or (left is not None and right is not None and all(
        left.get(key, UNDEFINED) == right.get(key, UNDEFINED)
        for key in ('provider', 'model', 'reasoningEffort')))


def _selection_state(state, event):
    if event['type'] == 'model/selection':
        return state if _same_selection(state['pending'], event['data']) else dict(state, pending=event['data'])
    if event['type'] != 'request/header':
        return state
    header = event['data']['header'];config = header['config']
    effort = (UNDEFINED if header.get('adapterDefaults', {}).get('reasoningEffort') is True
              else config.get('reasoningEffort', UNDEFINED))
    last = _selection(config['provider'], config['model'], effort)
    pending = None if _same_selection(state['pending'], last) else state['pending']
    return (state if _same_selection(state['lastUsed'], last) and pending is state['pending']
            else dict(lastUsed=last, pending=pending))


def _selection_schema(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError('model selection must be an object')
    keys = ('provider', 'model', 'reasoningEffort') if 'reasoningEffort' in value else ('provider', 'model')
    if any(not isinstance(value.get(key), str) or not value[key] for key in keys):
        raise TypeError('model selection fields must be nonempty strings')
    return {key: value[key] for key in keys}


MODEL_SELECTION_PROJECTION_DEFINITION = dict(
    key='modelSelection', stateVersion=3,
    stateSchema=lambda state: {key: _selection_schema(state[key]) for key in ('lastUsed', 'pending')},
    init=lambda *_: dict(lastUsed=None, pending=None), apply=_selection_state,
    wire=dict(viewSchema=lambda value: {key: _selection_schema(value[key]) for key in ('lastUsed', 'next')},
              view=lambda state: dict(lastUsed=state['lastUsed'], next=state['pending'] if state['pending'] is not None else state['lastUsed'])))
modelSelectionProjectionDefinition = MODEL_SELECTION_PROJECTION_DEFINITION


class AgentModel:
    """Read the driver's retained selection and persist explicit complete choices."""
    def __init__(self, read_state, session, options):
        self.read_state, self.session, self.options = read_state, session, options

    def _recorded(self):
        state = self.read_state()
        return state['pending'] if state['pending'] is not None else state['lastUsed']

    def current(self):
        recorded = self._recorded()
        if recorded is not None:
            return dict(recorded)
        options = self.options if isinstance(self.options, dict) else self.options.to_dict()
        return (_selection(options['provider'], options['model'], options.get('reasoningEffort', UNDEFINED))
                if options.get('provider') and options.get('model') else UNDEFINED)

    def select(self, selection):
        if _same_selection(self._recorded(), selection):
            return
        self.session.append('model/selection', _selection(selection['provider'], selection['model'],
                            selection.get('reasoningEffort', UNDEFINED)))


def _install_switch_notices(agent_ctx):
    from dsh.llm.message import create_user_message
    from dsh.cordis.awaiting import await_callback_result
    async def before_step(input, next_fn):
        decision = await await_callback_result(next_fn())
        if decision['kind'] == 'reject' or input['signal'].aborted:
            return decision
        if not decision['messages'] and (input['step'] == 1 or input['messages']):
            return decision
        header = input['agent'].session.requestHeader()
        selected = input['modelSelection']
        if header is None:
            return decision
        previous = header['config']
        if all(previous[key] == selected[key] for key in ('provider', 'model')):
            return decision
        def label(route, other):
            return route['model'] if route['provider'] == other['provider'] else route['provider'] + '/' + route['model']
        old, new = label(previous, selected), label(selected, previous)
        summary = old + ' → ' + new
        encoded = summary.encode('utf-16-le', 'surrogatepass')
        if len(encoded) > 240:
            summary = encoded[:238].decode('utf-16-le', 'surrogatepass') + '…'
        notice = create_user_message(dict(content=[dict(type='text', text=(
            '[model changed: assistant turns above this point were generated by %s; the session continues with %s]' % (old, new)))],
            source=dict(kind='model-selection', form='notice', summary=summary)))
        return dict(decision, messages=list(decision['messages']) + [notice])
    return agent_ctx.on('agent/pre-step', before_step, prepend=True)


AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE = settings_namespace("agent-default-model")


AGENT_DEFAULT_MODEL_SETTINGS_SCHEMA = z.object({
    "provider": z.string().required(),
    "model": z.string().required(),
    "reasoningEffort": z.string(),
})

class AgentDefaultModelConfig(Service):
    """Default Agent model selection layered over the optional settings service."""

    Config = z.object({"provider": z.string().required(), "model": z.string().required()})

    def __init__(self, ctx: Context, config: Dict[str, Any]):
        super().__init__(ctx, "agentDefaultModel")
        entry = {"provider": config["provider"], "model": config["model"]}
        self._source = lambda: entry

        def set_source(source: Callable[[], Dict[str, Any]]) -> None:
            self._source = source

        install_settings_section(
            ctx,
            AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE,
            AGENT_DEFAULT_MODEL_SETTINGS_SCHEMA,
            entry,
            {"setSource": set_source, "onChange": lambda: None},
        )

    def current_selection(self) -> Dict[str, Any]:
        settings = self._source()
        result = {"provider": settings["provider"], "model": settings["model"]}
        if "reasoningEffort" in settings:
            result["reasoningEffort"] = settings["reasoningEffort"]
        return result

    def currentSelection(self) -> Dict[str, Any]:
        return self.current_selection()

    async def save_selection(self, next_selection: Any) -> None:
        settings = self.ctx.get("settings", None)
        if settings is None:
            return
        if isinstance(next_selection, ModelSelection):
            value = next_selection.to_dict()
        else:
            value = next_selection
        section = {"provider": value["provider"], "model": value["model"]}
        if value.get("reasoningEffort") is not None:
            section["reasoningEffort"] = str(value["reasoningEffort"])
        result = settings.replace(AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE, section)
        if inspect.isawaitable(result):
            await result

    async def saveSelection(self, next_selection: Any) -> None:
        await self.save_selection(next_selection)


class ModelSelection:
    """Complete provider, model, and optional reasoning effort selected for one live Agent."""

    def __init__(
        self,
        provider: str,
        model: str,
        reasoning_effort: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model
        self.reasoning_effort = reasoning_effort

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
        }
        if self.reasoning_effort is not None:
            res["reasoningEffort"] = self.reasoning_effort
        return res


class ModelSelectionRef:
    """Mutable model selection plus the value captured for the current step."""

    def __init__(
        self,
        current: Optional[ModelSelection] = None,
        assembled: Optional[ModelSelection] = None,
    ):
        self.current = current
        self.assembled = assembled


def install_model_selection(agent_ctx: Context, selection: Optional[ModelSelectionRef] = None) -> Callable[[], None]:
    """
    Couple one mutable selection to Agent-scoped prompt assembly and request routing.
    """
    if selection is None:
        return _install_switch_notices(agent_ctx)
    import inspect

    async def _on_assembly(*args: Any, **kwargs: Any) -> Any:
        next_fn = args[-1] if args and callable(args[-1]) else None
        current_assembly = args[0] if args else {}
        selected = selection.current
        assembled = (await next_fn()) if (next_fn and inspect.iscoroutinefunction(next_fn)) else (next_fn() if next_fn else current_assembly)
        if inspect.isawaitable(assembled):
            assembled = await assembled
        selection.assembled = selected
        if selected is None:
            return assembled
        if isinstance(assembled, dict):
            res = dict(assembled)
            vars_dict = dict(res.get("variables", {}))
            vars_dict["provider"] = selected.provider
            vars_dict["model"] = selected.model
            res["variables"] = vars_dict
            return res
        return assembled

    async def _on_request(*args: Any, **kwargs: Any) -> Any:
        next_fn = args[-1] if args and callable(args[-1]) else None
        current_req = args[0] if args else {}
        resolved = (await next_fn()) if (next_fn and inspect.iscoroutinefunction(next_fn)) else (next_fn() if next_fn else current_req)
        if inspect.isawaitable(resolved):
            resolved = await resolved
        selected = selection.assembled
        if selected is None:
            return resolved
        if isinstance(resolved, dict):
            res = dict(resolved)
            res.pop("reasoningEffort", None)
            res["provider"] = selected.provider
            res["model"] = selected.model
            if selected.reasoning_effort is not None:
                res["reasoningEffort"] = selected.reasoning_effort
            return res
        return resolved

    dispose_assembly = agent_ctx.on("system-prompt/assemble", _on_assembly)
    dispose_request = agent_ctx.on("agent/request", _on_request)

    def disposer() -> None:
        dispose_assembly()
        dispose_request()

    return disposer


installModelSelection = install_model_selection
