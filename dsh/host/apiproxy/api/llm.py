"""
LLM Domain Handler (`@deepseek-ai/dsh-apiproxy/api/llm`).
Handles `llm.providers`, `llm.models`, `llm.discoverModels`.
Aligned 1:1 with reference `api/llm.ts`.
"""

from typing import Any, Dict


class LLMDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def list_providers(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        registered = llm.list_providers() if (llm and hasattr(llm, "list_providers")) else [
            {"id": "deepseek", "name": "DeepSeek Official"},
            {"id": "openai", "name": "OpenAI Compatible"}
        ]
        active = {p["id"] for p in registered}

        directory = llm.list_configurable_providers() if (llm and hasattr(llm, "list_configurable_providers")) else [
            {"provider": "deepseek", "displayName": "DeepSeek Official", "settingsNs": "llm", "settingsPath": []},
            {"provider": "openai", "displayName": "OpenAI Compatible", "settingsNs": "llm", "settingsPath": []}
        ]
        declared = {d["provider"] for d in directory}

        views = []
        for entry in directory:
            p_id = entry["provider"]
            view = {
                "provider": p_id,
                "displayName": entry.get("displayName", p_id),
                "settingsNs": entry.get("settingsNs", "llm"),
                "settingsPath": list(entry.get("settingsPath", [])),
                "active": p_id in active,
            }
            if "declared" in entry and entry["declared"] is not None:
                view["declared"] = entry["declared"]
            views.append(view)

        for p in registered:
            p_id = p["id"]
            if p_id not in declared:
                views.append({
                    "provider": p_id,
                    "displayName": p.get("name", p_id),
                    "settingsNs": "",
                    "settingsPath": [],
                    "active": True,
                })

        return {"providers": views}

    async def list_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        import inspect
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        providers = llm.list_providers() if (llm and hasattr(llm, "list_providers")) else [
            {"id": "deepseek", "name": "DeepSeek Official"}
        ]
        groups = []
        failures = []

        for provider in providers:
            p_id = provider["id"]
            p_name = provider.get("name", p_id)
            try:
                raw = llm.list_models(p_id) if (llm and hasattr(llm, "list_models")) else [
                    {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)", "description": "High efficiency general reasoning"},
                    {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)", "description": "Deep reasoning with explicit chain-of-thought"}
                ]
                models = await raw if inspect.isawaitable(raw) else raw
                entries = []
                for m in models:
                    entry = {
                        "id": m["id"],
                        "name": m.get("name", m["id"]),
                    }
                    if "description" in m and m["description"]:
                        entry["description"] = m["description"]
                    if "reasoning" in m and m["reasoning"]:
                        entry["reasoning"] = m["reasoning"]
                    if "contextWindow" in m and m["contextWindow"]:
                        entry["contextWindow"] = m["contextWindow"]
                    entries.append(entry)

                if entries:
                    groups.append({
                        "id": p_id,
                        "name": p_name,
                        "models": entries,
                    })
            except Exception as e:
                failures.append({
                    "id": p_id,
                    "name": p_name,
                    "message": str(e),
                })

        return {
            "groups": groups,
            "failures": failures,
        }

    async def discover_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        settings_ns = payload.get("settingsNs", "llm")
        if llm and hasattr(llm, "discover_models"):
            models = await llm.discover_models(settings_ns, payload)
        else:
            models = [
                {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)"},
                {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)"}
            ]
        return {"models": models}

