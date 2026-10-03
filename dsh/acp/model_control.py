import asyncio
import inspect
import json

from dsh.core.model_selection import ModelSelection, install_model_selection


def detached(selection):
    return None if selection is None else ModelSelection(selection.provider, selection.model, selection.reasoning_effort)


async def resolved(value):
    return await value if inspect.isawaitable(value) else value


def model_value(provider, model):
    return json.dumps([provider, model], ensure_ascii=False, separators=(',', ':'))


def selection_for(logged, fallback):
    if logged is None:
        return detached(fallback)
    config = logged['config']
    effort = None if logged.get('adapterDefaults', {}).get('reasoningEffort') is True else config.get('reasoningEffort')
    return ModelSelection(config['provider'], config['model'], effort)


class AcpModelConfigError(ValueError):
    pass


class SelectionRef:
    def __init__(self, control):
        self.control = control
        self.assembled = None

    @property
    def current(self):
        return self.control.turn_selection[1] if self.control.turn_selection is not None else self.control.selected

    @current.setter
    def current(self, value):
        self.control.selected = value


class AcpModelControl:
    def __init__(self, llm, initial=None):
        self.llm = llm
        self.selected = detached(initial)
        self.turn_selection = None
        self.has_resolved_state = False
        self.selection = SelectionRef(self)
        self.lock = asyncio.Lock()

    def install(self, agent_ctx):
        install_model_selection(agent_ctx, self.selection)

    def snapshot(self):
        return detached(self.selected)

    def pin_turn(self, turn, selection):
        self.turn_selection = (turn, detached(selection))

    def release_turn(self, turn):
        if self.turn_selection is not None and self.turn_selection[0] == turn:
            self.turn_selection = None

    async def options(self, signal=None):
        async with self.lock:
            return (await self._state(signal))[1]

    async def set(self, config_id, value, signal=None):
        async with self.lock:
            if not isinstance(value, str):
                raise AcpModelConfigError('%s requires a select value' % config_id)
            current = self.selected
            if current is None:
                raise AcpModelConfigError('this session has no model selection')
            if config_id == 'model':
                choices, options = await self._state(signal)
                selected = choices.get(value)
                if selected is None:
                    raise AcpModelConfigError('unknown model option: ' + value)
                await self._resolve_selection(selected, signal)
                self.selected = selected
            elif config_id == 'reasoning_effort':
                info = await resolved(self.llm.resolve_model_info(current.provider, current.model, signal))
                reasoning = info.get('reasoning')
                provider_default = value == '' and (reasoning or {}).get('defaultEffort') is None
                if reasoning is None or (not provider_default and not any(
                        effort['id'] == value for effort in reasoning['efforts'])):
                    raise AcpModelConfigError('unknown reasoning effort for %s/%s: %s' % (current.provider, current.model, value))
                self.selected = await self._resolve_selection(ModelSelection(current.provider, current.model,
                    None if provider_default else value), signal)
            else:
                raise AcpModelConfigError('unknown session config option: ' + config_id)
            return (await self._state(signal))[1]

    async def _resolve_selection(self, selection, signal):
        config = await resolved(self.llm.resolveCallConfig(selection.to_dict(), signal))
        return ModelSelection(config['provider'], config['model'], config.get('reasoningEffort'))

    async def _state(self, signal):
        if self.selected is None:
            return {}, []
        route_available = True
        try:
            selected = await self._resolve_selection(self.selected, signal)
        except Exception:
            if not self.has_resolved_state:
                raise
            selected = self.selected
            route_available = False
        self.has_resolved_state = True
        choices = {}

        async def group(provider):
            try:
                models = await resolved(self.llm.list_models(provider['id']))
            except Exception:
                models = []
            options = []
            for model in models:
                value = model_value(provider['id'], model['id'])
                choices[value] = ModelSelection(provider['id'], model['id'])
                option = {'value': value, 'name': model['name']}
                if model.get('description') is not None:
                    option['description'] = model['description']
                options.append(option)
            return {'group': provider['id'], 'name': provider['name'], 'options': options}

        groups = list(await asyncio.gather(*(group(provider) for provider in self.llm.listProviders())))
        current_value = model_value(selected.provider, selected.model)
        if current_value not in choices:
            choices[current_value] = ModelSelection(selected.provider, selected.model)
            current_group = next((item for item in groups if item['group'] == selected.provider), None)
            if current_group is None:
                current_group = {'group': selected.provider, 'name': selected.provider, 'options': []}
                groups.append(current_group)
            current_group['options'].insert(0, {'value': current_value, 'name': selected.model})
        options = [{'id': 'model', 'name': 'Model', 'category': 'model', 'type': 'select',
                    'currentValue': current_value, 'options': [item for item in groups if item['options']]}]
        info = await resolved(self.llm.resolve_model_info(selected.provider, selected.model, signal)) if route_available else None
        reasoning = info.get('reasoning') if info is not None else None
        if reasoning is not None:
            efforts = [] if reasoning.get('defaultEffort') is not None else [{'value': '', 'name': 'Provider default'}]
            for effort in reasoning['efforts']:
                option = {'value': str(effort['id']), 'name': effort['name']}
                if effort.get('description') is not None:
                    option['description'] = effort['description']
                efforts.append(option)
            options.append({'id': 'reasoning_effort', 'name': 'Reasoning effort', 'category': 'thought_level',
                'type': 'select', 'currentValue': '' if selected.reasoning_effort is None else str(selected.reasoning_effort),
                'options': efforts})
        return choices, options
