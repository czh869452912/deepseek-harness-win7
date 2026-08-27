import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.llm.error import HarnessError
from dsh.web.web_service import (
    WebError,
    WebFetchProvider,
    WebSearchProvider,
    WebService,
)


class SearchProvider:
    def __init__(self, provider_id, marker=None, available=True):
        self.id = provider_id
        self.marker = marker or provider_id
        self.usable = available
        self.calls = []

    def available(self):
        return self.usable

    async def search(self, request, signal=None):
        self.calls.append((request, signal))
        return {
            "content": self.marker,
            "sources": [
                {"url": "https://1.test"},
                {"url": "https://2.test"},
                {"url": "https://3.test"},
            ],
            "truncated": False,
        }


class FetchProvider:
    def __init__(self, provider_id, available=True):
        self.id = provider_id
        self.usable = available
        self.calls = []

    def available(self):
        return self.usable

    async def fetch(self, request, signal=None):
        self.calls.append((request, signal))
        return {
            "url": request["url"],
            "statusCode": 404,
            "body": {"kind": "text", "content": self.id},
            "truncated": False,
        }


async def mount(config=None):
    ctx = Context()
    fiber = ctx.registry.plugin(WebService, config or {}, parent_ctx=ctx)
    await fiber
    return ctx, ctx.get("web"), fiber


def assert_code(error, code):
    assert isinstance(error.value, WebError)
    assert isinstance(error.value, HarnessError)
    assert error.value.code == code


@pytest.mark.asyncio
async def test_canonical_registration_duplicate_namespaces_and_disposer():
    ctx, web, fiber = await mount()
    try:
        search = SearchProvider("shared")
        fetch = FetchProvider("shared")
        dispose = web.register_search_provider(search)
        web.register_fetch_provider(fetch)
        assert (await web.search({"query": "q"}))["content"] == "shared"
        assert (await web.fetch({"url": "https://example.test"}))["statusCode"] == 404
        with pytest.raises(WebError) as error:
            web.register_search_provider(SearchProvider("shared"))
        assert_code(error, "WEB_DUPLICATE_PROVIDER")
        dispose()
        replacement_dispose = web.register_search_provider(SearchProvider("shared", "replacement"))
        dispose()
        assert (await web.search({"query": "q"}))["content"] == "replacement"
        replacement_dispose()
        with pytest.raises(WebError) as error:
            await web.search({"query": "q"})
        assert_code(error, "WEB_PROVIDER_UNAVAILABLE")
    finally:
        await fiber.dispose()
    assert not ctx.has("web")


@pytest.mark.asyncio
async def test_provider_resolution_all_branches_and_dynamic_availability():
    _ctx, web, fiber = await mount()
    try:
        with pytest.raises(WebError) as error:
            await web.search({"query": "q"})
        assert_code(error, "WEB_PROVIDER_UNAVAILABLE")

        unavailable = SearchProvider("off", available=False)
        active = SearchProvider("on")
        web.register_search_provider(unavailable)
        with pytest.raises(WebError) as error:
            await web.search({"query": "q"})
        assert_code(error, "WEB_PROVIDER_UNAVAILABLE")
        dispose_active = web.register_search_provider(active)
        assert (await web.search({"query": "q"}))["content"] == "on"

        unavailable.usable = True
        with pytest.raises(WebError) as error:
            await web.search({"query": "q"})
        assert_code(error, "WEB_PROVIDER_AMBIGUOUS")
        dispose_active()
        assert (await web.search({"query": "q"}))["content"] == "off"
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("configured, registered, usable, code", [
    ("missing", "other", True, "WEB_PROVIDER_CONFIGURED_MISSING"),
    ("selected", "selected", False, "WEB_PROVIDER_CONFIGURED_UNAVAILABLE"),
])
async def test_configured_provider_failure_codes(configured, registered, usable, code):
    _ctx, web, fiber = await mount({"searchProvider": configured})
    try:
        web.register_search_provider(SearchProvider(registered, available=usable))
        with pytest.raises(WebError) as error:
            await web.search({"query": "q"})
        assert_code(error, code)
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_configured_provider_wins_and_explicit_config_wins_environment(monkeypatch):
    monkeypatch.setenv("DSH_WEB_SEARCH_PROVIDER", "environment")
    _ctx, web, fiber = await mount({"searchProvider": "configured"})
    try:
        web.register_search_provider(SearchProvider("environment"))
        web.register_search_provider(SearchProvider("configured"))
        assert (await web.search({"query": "q"}))["content"] == "configured"
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_signal_forwarding_result_contract_and_max_results_cap():
    _ctx, web, fiber = await mount()
    provider = SearchProvider("search")
    web.register_search_provider(provider)
    signal = asyncio.Event()
    try:
        result = await web.search({"query": "q", "maxResults": 2}, signal)
        assert provider.calls == [({"query": "q", "maxResults": 2}, signal)]
        assert result == {
            "content": "search",
            "sources": [{"url": "https://1.test"}, {"url": "https://2.test"}],
            "truncated": True,
        }
        uncapped = await web.search({"query": "q"}, signal)
        assert len(uncapped["sources"]) == 3
        assert uncapped["truncated"] is False
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_uncapped_canonical_results_preserve_provider_identity_and_parameter_names():
    class ArbitraryNamesSearch(WebSearchProvider):
        id = "search"

        def available(self):
            return True

        async def search(self, _request, _signal=None):
            return search_result

    class ArbitraryNamesFetch(WebFetchProvider):
        id = "fetch"

        def available(self):
            return True

        async def fetch(self, _request, _signal=None):
            return fetch_result

    search_result = {"sources": [], "truncated": False}
    fetch_result = {"url": "https://example.test", "statusCode": 200,
                    "body": {"kind": "text", "content": "ok"},
                    "truncated": False}
    _ctx, web, fiber = await mount()
    try:
        web.register_search_provider(ArbitraryNamesSearch())
        web.register_fetch_provider(ArbitraryNamesFetch())
        assert await web.search({"query": "q"}) is search_result
        assert await web.fetch({"url": "https://example.test"}) is fetch_result
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_fetch_selection_is_independent_and_forwards_signal():
    _ctx, web, fiber = await mount({"fetchProvider": "http"})
    provider = FetchProvider("http")
    signal = asyncio.Event()
    try:
        web.register_search_provider(SearchProvider("search"))
        web.register_fetch_provider(provider)
        result = await web.fetch({"url": "https://example.test"}, signal)
        assert result["body"]["content"] == "http"
        assert provider.calls == [({"url": "https://example.test"}, signal)]
    finally:
        await fiber.dispose()


class ContributingPlugin(Plugin):
    inject = ["web"]

    def apply(self, ctx):
        ctx.web.register_search_provider(SearchProvider("owned"))


@pytest.mark.asyncio
async def test_registration_is_owned_by_contributing_fiber():
    ctx, web, web_fiber = await mount()
    contributor = ctx.registry.plugin(ContributingPlugin, parent_ctx=ctx)
    await contributor
    try:
        assert (await web.search({"query": "q"}))["content"] == "owned"
        await contributor.dispose()
        with pytest.raises(WebError) as error:
            await web.search({"query": "q"})
        assert_code(error, "WEB_PROVIDER_UNAVAILABLE")
    finally:
        await web_fiber.dispose()


class LegacySearch(WebSearchProvider):
    async def search(self, query, max_results=10, timeout_ms=60000):
        return [{"url": "https://legacy.test", "title": query}]


def test_legacy_registration_signature_remains_an_explicit_adapter():
    web = WebService()
    dispose = web.register_search_provider("legacy", LegacySearch())
    assert callable(dispose)
    assert "legacy" in web.search_providers
    dispose()
    assert "legacy" not in web.search_providers


@pytest.mark.parametrize("config", [
    {"searchProvider": 1},
    {"fetchProvider": False},
])
def test_provider_selection_config_accepts_only_strings(config):
    with pytest.raises(ValueError, match="must be a string"):
        WebService(config)
