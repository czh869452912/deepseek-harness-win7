from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class WebSearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 10, timeout_ms: int = 60000) -> List[Dict[str, Any]]:
        pass


class WebFetchProvider(ABC):
    @abstractmethod
    async def fetch(self, url: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        pass


class WebService:
    def __init__(self):
        self.search_providers: Dict[str, WebSearchProvider] = {}
        self.fetch_providers: Dict[str, WebFetchProvider] = {}
        self.default_search: Optional[str] = None
        self.default_fetch: Optional[str] = None

    def register_search_provider(self, name: str, provider: WebSearchProvider) -> None:
        self.search_providers[name] = provider
        if not self.default_search:
            self.default_search = name

    def register_fetch_provider(self, name: str, provider: WebFetchProvider) -> None:
        self.fetch_providers[name] = provider
        if not self.default_fetch:
            self.default_fetch = name

    async def search(self, query: str, max_results: int = 10, timeout_ms: int = 60000) -> List[Dict[str, Any]]:
        if not self.default_search or self.default_search not in self.search_providers:
            raise RuntimeError("No active web search provider registered")
        return await self.search_providers[self.default_search].search(query, max_results, timeout_ms)

    async def fetch(self, url: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        if not self.default_fetch or self.default_fetch not in self.fetch_providers:
            raise RuntimeError("No active web fetch provider registered")
        return await self.fetch_providers[self.default_fetch].fetch(url, timeout_ms)
