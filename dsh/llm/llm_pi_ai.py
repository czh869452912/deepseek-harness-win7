"""Formal pi-ai provider ownership, live settings, and model discovery."""
import copy
import logging

from dsh.cordis.plugin import Plugin
from dsh.llm.pi_adapter import PiAiAdapter, native_profiles
from dsh.llm.pi_auth import resolve_api_key
from dsh.llm.pi_catalog import catalog_provider_ids
from dsh.llm.pi_discovery import discover_models
from dsh.llm.pi_schema import config_schema
from dsh.settings.provider import deep_equal_json, install_settings_section


def directory_entries(profiles):
    catalog = catalog_provider_ids()
    names = {provider: provider for provider in catalog}
    names.update({provider: profile['displayName'] for provider, profile in profiles.items()})
    return [dict(provider=provider, displayName=name, settingsNs='llm-pi-ai',
                 settingsPath=['providers', provider], declared=provider not in catalog)
            for provider, name in names.items()]


class LLMPiAiPlugin(Plugin):
    id = 'llm-pi-ai'
    inject = ['llm']
    Config = config_schema()

    def apply(self, ctx):
        llm = ctx.get('llm')
        entry = copy.deepcopy(self.config or {})
        adapter = PiAiAdapter(ctx, native_profiles(entry))
        ctx.effect(lambda: adapter.close)
        source = [lambda: entry]
        registration = [None]
        directory = llm.register_configurable_providers(directory_entries(adapter.profiles))
        ctx.effect(lambda: directory)
        previous = [None]

        def refresh():
            raw = source[0]()
            if deep_equal_json(raw, previous[0]):
                return
            candidate = native_profiles(raw)
            old = adapter.profiles
            adapter.profiles = candidate
            try:
                if registration[0] is None and candidate:
                    registration[0] = llm.register_adapter(list(candidate), adapter)
                elif registration[0] is not None:
                    registration[0].replace(list(candidate))
            except Exception:
                adapter.profiles = old
                raise
            try:
                directory.replace(directory_entries(candidate))
            except Exception:
                logging.getLogger('llm-pi-ai').exception('Keeping the previous configurable-provider directory')
            previous[0] = copy.deepcopy(raw)

        def changed():
            try:
                refresh()
            except Exception:
                logging.getLogger('llm-pi-ai').exception('Keeping the previously registered routes after a refused update')

        def dispose_routes():
            if registration[0] is not None:
                registration[0]()

        ctx.effect(lambda: dispose_routes)
        refresh()

        async def discover(request, signal=None):
            async def stored_key():
                provider = request.get('provider')
                profile = adapter.profiles.get(provider)
                return await resolve_api_key(ctx, provider, profile, ambient=False) if profile is not None else None
            return await discover_models(dict(request, signal=signal), stored_key)

        disposer = llm.register_model_discovery('llm-pi-ai', discover)
        ctx.effect(lambda: disposer)
        install_settings_section(ctx, 'llm-pi-ai', self.Config, entry, dict(validate=native_profiles,
            setSource=lambda current: source.__setitem__(0, current), onChange=changed))
