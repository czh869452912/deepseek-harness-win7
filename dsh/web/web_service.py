"""Provider-selecting web capability service matching ``@deepseek-ai/dsh-web``."""

import asyncio
import inspect
import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Callable, Dict, Optional, Tuple

from dsh.cordis.service import Service
from dsh.llm.error import HarnessError


class WebError(HarnessError):
    """Typed web error with a stable, machine-routable code."""


class WebSearchProvider(ABC):
    """Canonical search provider protocol base."""

    id = ""

    def available(self) -> bool:
        return True

    @abstractmethod
    async def search(self, request: Dict[str, Any], signal: Any = None) -> Any:
        pass


class WebFetchProvider(ABC):
    """Canonical fetch provider protocol base."""

    id = ""

    def available(self) -> bool:
        return True

    @abstractmethod
    async def fetch(self, request: Dict[str, Any], signal: Any = None) -> Any:
        pass


def _parameter_names(callback: Callable[..., Any]) -> Tuple[str, ...]:
    try:
        return tuple(inspect.signature(callback).parameters)
    except (TypeError, ValueError):
        return ()


def _provider_available(provider: Any) -> bool:
    callback = getattr(provider, "available", None)
    return bool(callback()) if callable(callback) else True


class WebService(Service):
    """Search/fetch registries with deterministic execution-time selection."""

    name = "web"
    provide_name = "web"

    def __init__(self, ctx: Optional[Any] = None,
                 config: Optional[Dict[str, Any]] = None):
        if isinstance(ctx, dict) and config is None:
            config = ctx
            ctx = None
        cfg = dict(config or {})
        for key in ("searchProvider", "fetchProvider"):
            if key in cfg and not isinstance(cfg[key], str):
                raise ValueError("web: %s must be a string" % key)
        self.search_provider_id = (cfg["searchProvider"]
                                   if "searchProvider" in cfg
                                   else os.environ.get("DSH_WEB_SEARCH_PROVIDER"))
        self.fetch_provider_id = (cfg["fetchProvider"]
                                  if "fetchProvider" in cfg
                                  else os.environ.get("DSH_WEB_FETCH_PROVIDER"))
        self.search_providers: Dict[str, Any] = {}
        self.fetch_providers: Dict[str, Any] = {}
        self._legacy_search_providers: Dict[str, bool] = {}
        self._legacy_fetch_providers: Dict[str, bool] = {}
        if ctx is not None:
            super().__init__(ctx, "web")
        else:
            self.ctx = None

    @property
    def default_search(self) -> Optional[str]:
        return self._legacy_selected_id(self.search_provider_id,
                                        self.search_providers)

    @property
    def default_fetch(self) -> Optional[str]:
        return self._legacy_selected_id(self.fetch_provider_id,
                                        self.fetch_providers)

    @staticmethod
    def _legacy_selected_id(configured: Optional[str],
                            providers: Dict[str, Any]) -> Optional[str]:
        if configured in providers:
            return configured
        return next(iter(providers), None)

    def register_search_provider(self, provider_or_id: Any,
                                 provider: Any = None) -> Callable[[], None]:
        legacy = provider is not None
        provider_id, value = self._registration(provider_or_id, provider)
        return self._register_provider(
            self.search_providers, self._legacy_search_providers,
            provider_id, value, legacy,
        )

    def register_fetch_provider(self, provider_or_id: Any,
                                provider: Any = None) -> Callable[[], None]:
        legacy = provider is not None
        provider_id, value = self._registration(provider_or_id, provider)
        return self._register_provider(
            self.fetch_providers, self._legacy_fetch_providers,
            provider_id, value, legacy,
        )

    registerSearchProvider = register_search_provider
    registerFetchProvider = register_fetch_provider

    @staticmethod
    def _registration(provider_or_id: Any, provider: Any) -> Tuple[str, Any]:
        if provider is None:
            value = provider_or_id
            provider_id = getattr(value, "id", None)
        else:
            provider_id = provider_or_id
            value = provider
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("web provider id must be a non-empty string")
        return provider_id, value

    def _register_provider(self, store: Dict[str, Any],
                           legacy_store: Dict[str, bool], provider_id: str,
                           provider: Any, legacy: bool) -> Callable[[], None]:
        if provider_id in store:
            raise WebError('a web provider with id "%s" is already registered' % provider_id,
                           "WEB_DUPLICATE_PROVIDER")
        store[provider_id] = provider
        legacy_store[provider_id] = legacy
        active = [True]

        def cleanup() -> None:
            if active[0] and store.get(provider_id) is provider:
                del store[provider_id]
                legacy_store.pop(provider_id, None)
            active[0] = False

        effect_disposer = None
        owner_ctx = getattr(self, "ctx", None)
        if owner_ctx is not None and callable(getattr(owner_ctx, "effect", None)):
            try:
                effect_disposer = owner_ctx.effect(lambda: cleanup,
                                                   label="web.registerProvider()")
            except Exception:
                cleanup()
                raise

        def dispose() -> None:
            cleanup()
            if effect_disposer is None:
                return
            pending = effect_disposer()
            if not inspect.isawaitable(pending):
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(pending)
            else:
                loop.create_task(pending)

        return dispose

    def _resolve_provider(self, store: Dict[str, Any],
                          configured_id: Optional[str]) -> Tuple[str, Any]:
        if configured_id is not None:
            provider = store.get(configured_id)
            if provider is None:
                raise WebError('configured web provider "%s" is not registered' % configured_id,
                               "WEB_PROVIDER_CONFIGURED_MISSING")
            if not _provider_available(provider):
                raise WebError('configured web provider "%s" is registered but unavailable' % configured_id,
                               "WEB_PROVIDER_CONFIGURED_UNAVAILABLE")
            return configured_id, provider
        usable = [(provider_id, provider) for provider_id, provider in store.items()
                  if _provider_available(provider)]
        if not usable:
            raise WebError("no usable web provider is registered",
                           "WEB_PROVIDER_UNAVAILABLE")
        if len(usable) > 1:
            raise WebError(
                "multiple usable web providers are registered (%s); configure one explicitly" %
                ", ".join(provider_id for provider_id, _provider in usable),
                "WEB_PROVIDER_AMBIGUOUS",
            )
        return usable[0]

    async def search(self, request: Any, signal: Any = None,
                     max_results: Optional[int] = None,
                     timeout_ms: int = 60000) -> Any:
        legacy_call = isinstance(request, str)
        canonical_request = ({"query": request, "maxResults": max_results}
                             if legacy_call and max_results is not None
                             else {"query": request} if legacy_call
                             else dict(request))
        provider_id, provider = self._resolve_provider(
            self.search_providers, self.search_provider_id)
        callback = provider.search
        canonical_provider = not self._legacy_search_providers[provider_id]
        if canonical_provider:
            result = await callback(canonical_request, signal)
        else:
            names = _parameter_names(callback)
            kwargs = {"signal": signal} if "signal" in names else {}
            result = await callback(canonical_request["query"],
                                    canonical_request.get("maxResults", 10),
                                    **kwargs)
        if legacy_call:
            return result
        normalized = (result if canonical_provider else
                      self._normalize_search_result(result))
        cap = canonical_request.get("maxResults")
        if cap is None or len(normalized["sources"]) <= cap:
            return normalized
        capped = dict(normalized)
        capped["sources"] = list(normalized["sources"][:cap])
        capped["truncated"] = True
        return capped

    async def fetch(self, request: Any, signal: Any = None,
                    timeout_ms: int = 30000) -> Any:
        legacy_call = isinstance(request, str)
        canonical_request = {"url": request} if legacy_call else dict(request)
        provider_id, provider = self._resolve_provider(
            self.fetch_providers, self.fetch_provider_id)
        callback = provider.fetch
        canonical_provider = not self._legacy_fetch_providers[provider_id]
        if canonical_provider:
            result = await callback(canonical_request, signal)
        else:
            names = _parameter_names(callback)
            kwargs = {"signal": signal} if "signal" in names else {}
            result = await callback(canonical_request["url"], **kwargs)
        if legacy_call:
            return result
        if canonical_provider:
            return result
        return self._normalize_fetch_result(result, canonical_request["url"])

    @staticmethod
    def _normalize_search_result(result: Any) -> Dict[str, Any]:
        if isinstance(result, list):
            return {"sources": list(result), "truncated": False}
        if not isinstance(result, Mapping):
            raise TypeError("web search provider returned an invalid result")
        return dict(result)

    @staticmethod
    def _normalize_fetch_result(result: Any, requested_url: str) -> Dict[str, Any]:
        if not isinstance(result, Mapping):
            raise TypeError("web fetch provider returned an invalid result")
        if isinstance(result.get("body"), Mapping):
            return dict(result)
        return {
            "url": result.get("url", requested_url),
            "statusCode": result.get("statusCode", result.get("status", 200)),
            "body": {"kind": "text", "content": result.get("content", "")},
            "truncated": bool(result.get("truncated", False)),
        }


WebRuntime = WebService


__all__ = [
    "WebError", "WebFetchProvider", "WebRuntime", "WebSearchProvider",
    "WebService",
]
