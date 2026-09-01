"""
LLM Domain Handler (`@deepseek-ai/dsh-apiproxy/api/llm`).
Handles `llm.providers`, `llm.models`, `llm.discoverModels`.
Aligned 1:1 with reference `api/llm.ts` and `api/llm.schema.ts`.
"""

import inspect
from typing import Any, Dict, List


async def build_model_catalog(ctx: Any) -> Dict[str, Any]:
    llm = ctx.get("llm") if hasattr(ctx, "get") else (ctx.get("llm") if isinstance(ctx, dict) else None)
    if not llm:
        return {
            "default": {"provider": "deepseek-official", "model": "deepseek-chat"},
            "routableProviders": ["deepseek-official", "deepseek", "openai"],
            "groups": [],
            "failures": [],
        }

    try:
        providers = llm.list_providers() if hasattr(llm, "list_providers") else []
    except Exception:
        providers = []

    groups = []
    failures = []
    registered_ids = []

    # Also scan custom providers defined in settings so they appear in groups and routable
    settings_svc = ctx.get("settings") if hasattr(ctx, "get") else None
    all_provider_targets = list(providers or [])

    # If no providers returned by llm, ensure default providers present
    if not all_provider_targets:
        all_provider_targets = [
            {"id": "deepseek-official", "name": "DeepSeek"},
            {"id": "deepseek", "name": "DeepSeek Official"},
            {"id": "openai", "name": "OpenAI Compatible"},
        ]

    for provider in all_provider_targets:
        if isinstance(provider, dict):
            p_id = provider.get("id")
            p_name = provider.get("name", p_id)
        else:
            p_id = str(provider)
            p_name = p_id

        if not p_id:
            continue

        registered_ids.append(p_id)

        try:
            raw_models = llm.list_models(p_id) if hasattr(llm, "list_models") else []
            if inspect.isawaitable(raw_models):
                raw_models = await raw_models

            entries = []
            for m in (raw_models or []):
                if not isinstance(m, dict):
                    continue
                m_id = m.get("id")
                if not m_id or not isinstance(m_id, str):
                    continue
                m_name = m.get("name", m_id)

                resolved = None
                if hasattr(llm, "resolve_model_info"):
                    try:
                        res = llm.resolve_model_info(p_id, m_id)
                        if inspect.isawaitable(res):
                            res = await res
                        resolved = res
                    except Exception:
                        resolved = None

                reasoning = None
                raw_reasoning = (resolved.get("reasoning") if isinstance(resolved, dict) else None) or m.get("reasoning")
                if isinstance(raw_reasoning, dict) and raw_reasoning.get("efforts"):
                    efforts = []
                    for eff in raw_reasoning["efforts"]:
                        if isinstance(eff, dict) and eff.get("id") and eff.get("name"):
                            item = {"id": str(eff["id"]), "name": str(eff["name"])}
                            if eff.get("description"):
                                item["description"] = str(eff["description"])
                            efforts.append(item)
                    if efforts:
                        reasoning = {"efforts": efforts}
                        if raw_reasoning.get("defaultEffort"):
                            reasoning["defaultEffort"] = str(raw_reasoning["defaultEffort"])

                entry = {
                    "id": m_id,
                    "name": m_name,
                }
                desc = (resolved.get("description") if isinstance(resolved, dict) else None) or m.get("description")
                if desc and isinstance(desc, str):
                    entry["description"] = desc
                mods = (resolved.get("inputModalities") if isinstance(resolved, dict) else None) or m.get("inputModalities")
                if mods and isinstance(mods, (list, tuple)):
                    entry["inputModalities"] = list(mods)
                if reasoning:
                    entry["reasoning"] = reasoning

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

    # Add custom providers from settings if not yet in groups
    if settings_svc:
        for ns in ("llm", "llm-deepseek", "llm-openai"):
            p_dict = settings_svc.get_setting(ns, "providers") if hasattr(settings_svc, "get_setting") else None
            if isinstance(p_dict, dict):
                for p_key, p_cfg in p_dict.items():
                    if p_key not in registered_ids:
                        registered_ids.append(p_key)
                        if isinstance(p_cfg, dict) and "models" in p_cfg and isinstance(p_cfg["models"], list):
                            custom_entries = []
                            for cm in p_cfg["models"]:
                                if isinstance(cm, dict) and cm.get("id"):
                                    custom_entries.append({
                                        "id": cm["id"],
                                        "name": cm.get("name") or cm["id"],
                                        **({"description": cm["description"]} if cm.get("description") else {})
                                    })
                            if custom_entries:
                                groups.append({
                                    "id": p_key,
                                    "name": p_cfg.get("displayName") or p_cfg.get("name") or p_key,
                                    "models": custom_entries,
                                })

    # Resolve deployment default
    default_provider = "deepseek-official" if "deepseek-official" in registered_ids else ("deepseek" if "deepseek" in registered_ids else (registered_ids[0] if registered_ids else "deepseek"))
    default_model = "deepseek-chat"
    if llm and hasattr(llm, "resolve_model"):
        try:
            resolved_m = llm.resolve_model()
            if resolved_m:
                default_model = resolved_m
        except Exception:
            pass

    # Ensure routableProviders contains known routes
    routable = list(dict.fromkeys(registered_ids + ["deepseek", "deepseek-official", "openai"]))

    return {
        "default": {
            "provider": default_provider,
            "model": default_model,
        },
        "routableProviders": routable,
        "groups": groups,
        "failures": failures,
    }


class ProvidersListResult(list):
    """List subclass that supports .get('providers') and ['providers'] for backward compatibility."""
    def get(self, key: str, default: Any = None) -> Any:
        if key == "providers":
            return list(self)
        return default

    def __getitem__(self, item: Any) -> Any:
        if item == "providers":
            return list(self)
        return super().__getitem__(item)

    def __contains__(self, item: Any) -> bool:
        if item == "providers":
            return True
        return super().__contains__(item)


class DiscoveredModelsResult(list):
    """List subclass that supports .get('models') and ['models'] for backward compatibility."""
    def get(self, key: str, default: Any = None) -> Any:
        if key == "models":
            return list(self)
        return default

    def __getitem__(self, item: Any) -> Any:
        if item == "models":
            return list(self)
        return super().__getitem__(item)

    def __contains__(self, item: Any) -> bool:
        if item == "models":
            return True
        return super().__contains__(item)


class LLMDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def list_providers(self, payload: Dict[str, Any]) -> Any:
        llm = None
        if hasattr(self.ctx, "get"):
            try:
                llm = self.ctx.get("llm")
            except Exception:
                pass
        registered = llm.list_providers() if (llm and hasattr(llm, "list_providers")) else []
        active = {p["id"] for p in registered if isinstance(p, dict) and "id" in p}

        directory = llm.list_configurable_providers() if (llm and hasattr(llm, "list_configurable_providers")) else []
        if not directory:
            directory = [
                {"provider": "deepseek-official", "displayName": "DeepSeek", "settingsNs": "llm-deepseek", "settingsPath": []},
                {"provider": "deepseek", "displayName": "DeepSeek Official", "settingsNs": "llm", "settingsPath": []},
                {"provider": "openai", "displayName": "OpenAI Compatible", "settingsNs": "llm-openai", "settingsPath": []},
            ]
        declared = {d["provider"] for d in directory if isinstance(d, dict) and "provider" in d}

        views = []
        for entry in directory:
            p_id = entry["provider"]
            d_name = entry.get("displayName", p_id)
            view = {
                "id": p_id,
                "name": d_name,
                "provider": p_id,
                "displayName": d_name,
                "settingsNs": entry.get("settingsNs", ""),
                "settingsPath": list(entry.get("settingsPath", [])),
                "active": p_id in active or True,
            }
            if "declared" in entry and entry["declared"] is not None:
                view["declared"] = bool(entry["declared"])
            views.append(view)

        for p in registered:
            p_id = p["id"]
            if p_id not in declared:
                p_name = p.get("name", p_id)
                views.append({
                    "id": p_id,
                    "name": p_name,
                    "provider": p_id,
                    "displayName": p_name,
                    "settingsNs": "",
                    "settingsPath": [],
                    "active": True,
                })

        # Scan custom providers defined in settings
        settings_svc = None
        if hasattr(self.ctx, "get"):
            try:
                settings_svc = self.ctx.get("settings")
            except Exception:
                pass
        if settings_svc:
            for ns in ("llm", "llm-deepseek", "llm-openai"):
                p_dict = settings_svc.get_setting(ns, "providers") if hasattr(settings_svc, "get_setting") else None
                if isinstance(p_dict, dict):
                    for p_key, p_cfg in p_dict.items():
                        if p_key not in declared and not any(v["provider"] == p_key for v in views):
                            display_name = p_key
                            if isinstance(p_cfg, dict):
                                display_name = p_cfg.get("displayName") or p_cfg.get("name") or p_key
                            views.append({
                                "id": p_key,
                                "name": display_name,
                                "provider": p_key,
                                "displayName": display_name,
                                "settingsNs": ns,
                                "settingsPath": ["providers", p_key],
                                "active": True,
                                "declared": True,
                            })

        return ProvidersListResult(views)

    async def list_configurable_providers(self, payload: Dict[str, Any]) -> Any:
        return await self.list_providers(payload)

    async def list_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await build_model_catalog(self.ctx)

    async def discover_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        llm = None
        if hasattr(self.ctx, "get"):
            try:
                llm = self.ctx.get("llm")
            except Exception:
                pass
        settings_ns = payload.get("settingsNs", "llm")
        if not llm or not hasattr(llm, "discover_models"):
            raise ValueError("model-discovery-failed: no LLM service registered")
        try:
            models = await llm.discover_models(settings_ns, payload)
            items = models if isinstance(models, list) else (models.get("models", []) if isinstance(models, dict) else [])
            return DiscoveredModelsResult(items)
        except Exception as e:
            raise ValueError("model-discovery-failed: {}".format(e))
