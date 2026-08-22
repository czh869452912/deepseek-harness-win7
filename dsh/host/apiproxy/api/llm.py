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
        return {"groups": [], "failures": []}

    try:
        providers = llm.list_providers() if hasattr(llm, "list_providers") else []
    except Exception:
        providers = []

    groups = []
    failures = []

    for provider in (providers or []):
        if isinstance(provider, dict):
            p_id = provider.get("id")
            p_name = provider.get("name", p_id)
        else:
            p_id = str(provider)
            p_name = p_id

        if not p_id:
            continue

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

    return {"groups": groups, "failures": failures}


class LLMDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def list_providers(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        registered = llm.list_providers() if (llm and hasattr(llm, "list_providers")) else []
        active = {p["id"] for p in registered if isinstance(p, dict) and "id" in p}

        directory = llm.list_configurable_providers() if (llm and hasattr(llm, "list_configurable_providers")) else []
        declared = {d["provider"] for d in directory if isinstance(d, dict) and "provider" in d}

        views = []
        for entry in directory:
            p_id = entry["provider"]
            view = {
                "provider": p_id,
                "displayName": entry.get("displayName", p_id),
                "settingsNs": entry.get("settingsNs", ""),
                "settingsPath": list(entry.get("settingsPath", [])),
                "active": p_id in active,
            }
            if "declared" in entry and entry["declared"] is not None:
                view["declared"] = bool(entry["declared"])
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

        # Scan custom providers defined in settings
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
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
                                "provider": p_key,
                                "displayName": display_name,
                                "settingsNs": ns,
                                "settingsPath": ["providers", p_key],
                                "active": p_key in active,
                                "declared": True,
                            })

        return {"providers": views}

    async def list_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await build_model_catalog(self.ctx)

    async def discover_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        settings_ns = payload.get("settingsNs", "llm")
        if not llm or not hasattr(llm, "discover_models"):
            raise ValueError("model-discovery-failed: no LLM service registered")
        try:
            models = await llm.discover_models(settings_ns, payload)
            return {"models": models}
        except Exception as e:
            raise ValueError("model-discovery-failed: {}".format(e))
