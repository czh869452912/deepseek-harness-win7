"""rc.3 persona framing; activated with the coordinated profile migration."""
from .service import SystemPrompt
from .types import FIRST_PARTY_SECTION_ORDER as _previous, _FirstPartySectionOrder


FIRST_PARTY_SECTION_ORDER = _FirstPartySectionOrder(
    (key, value) for key, value in _previous.items() if key != 'DEPLOYMENT_PERSONA')
FIRST_PARTY_SECTION_ORDER.update(DEPLOYMENT_PERSONA_PREFIX=0, HARNESS_SOURCE=10000,
                                WEB_SURFACE=10100, DEPLOYMENT_PERSONA_SUFFIX=10200, TOOL_APPLY_PATCH=1350,
                                TOOL_PTY_PANEL=1710, TOOL_SCHEDULE=2500, TOOL_COMPUTER_USE=3000, MCP_SERVERS=3100)
PERSONA_PREFIX_SECTION = 'deployment:persona-prefix'
PERSONA_SUFFIX_SECTION = 'deployment:persona-suffix'


class CurrentSystemPrompt(SystemPrompt):
    _section_orders = FIRST_PARTY_SECTION_ORDER
    _authoritative_tools = True

    def get_context_order(self, name):
        return dict(WORKING_DIRECTORY=100, SANDBOX_POLICY=110, APPROVAL_POLICY=115,
                    SUBAGENT_DELEGATION=120, HARNESS_SOURCE=200, WEB_SURFACE=210)[name]

    getContextOrder = get_context_order

    def _persona_sections(self, config):
        return [dict(name=PERSONA_PREFIX_SECTION, order=0, text=config.get('personaPrefix', '')),
                dict(name=PERSONA_SUFFIX_SECTION, order=10200, text=config.get('personaSuffix', ''))]

    def refresh_context(self, assembly, context=None):
        context = context or {}
        scope = context.get('scope')
        providers = self.layers.merge(scope, lambda layer: layer.contexts)
        suppressed = (not self.layers.global_layer.runtime_context_suppressors.is_empty()
                      or any(not layer.runtime_context_suppressors.is_empty()
                             for layer in self.layers.chain_layers(scope)))
        required = {name: entry for name, entry in providers.items() if entry.required is True}
        contexts = []
        def resolve(entry):
            resolved = dict(name=entry.name, text=entry.text(context) if callable(entry.text) else entry.text)
            if getattr(entry, 'interpolate', None) is not None:
                resolved['interpolate'] = entry.interpolate
            return resolved
        for accepted in assembly['contexts']:
            provider = providers.get(accepted['name'])
            required.pop(accepted['name'], None)
            if suppressed and (provider is None or provider.required is not True):
                continue
            contexts.append(accepted if provider is None else resolve(provider))
        for provider in required.values():
            index = next((index for index, entry in enumerate(contexts)
                          if entry['name'] in providers and providers[entry['name']].order > provider.order), len(contexts))
            contexts.insert(index, resolve(provider))
        return dict(assembly, contexts=contexts)

    refreshContext = refresh_context
