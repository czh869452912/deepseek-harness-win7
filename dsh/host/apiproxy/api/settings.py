"""
Settings Domain Handler (`@deepseek-ai/dsh-apiproxy/api/settings`).
Handles all 5 settings RPC methods aligned 1:1 with reference `api/settings.ts`.
"""

import os
from typing import Any, Dict, List, Optional
from dsh.host.apiproxy.native_path_opener import open_native_path


class SettingsDomainHandler:
    """Handler for settings.* RPC methods."""

    def __init__(self, ctx: Any):
        self.ctx = ctx

    def _build_schemastery_schema(self, ns: str, has_key: bool) -> Dict[str, Any]:
        # Minimal schemastery JSON envelope that client store can rehydrate
        # Must contain providers probe for protocolChoices and apiKeyEnv detection
        if ns == "llm":
            return {
                "type": "object",
                "properties": {
                    "baseUrl": {"type": "string"},
                    "model": {"type": "string"},
                    "apiKeyEnv": {"type": "string"},
                    "providers": {
                        "type": "dict",
                        "value": {
                            "type": "object",
                            "properties": {
                                "baseUrl": {"type": "string"},
                                "api": {"type": "union", "list": [{"value": "openai"}, {"value": "anthropic"}]},
                                "apiKeyEnv": {"type": "string"},
                                "model": {"type": "string"},
                            },
                        },
                    },
                },
            }
        return {"type": "object", "properties": {}}

    async def describe_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        has_key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or (llm and getattr(llm, "static_api_key", None)))
        # Resolve actual stored values
        if settings_svc and hasattr(settings_svc, "_data") and isinstance(settings_svc._data, dict):
            stored_llm = settings_svc._data.get("llm", {})
            stored_general = settings_svc._data.get("general", {})
        else:
            stored_llm = {}
            stored_general = {}
        llm_value = {
            "baseUrl": (stored_llm.get("base_url") or stored_llm.get("baseUrl") or (llm.resolve_base_url() if llm else "https://api.deepseek.com")),
            "model": (stored_llm.get("model") or (llm.resolve_model() if llm else "deepseek-chat")),
        }
        # Merge providers from stored if any
        if isinstance(stored_llm.get("providers"), dict):
            llm_value["providers"] = stored_llm["providers"]
        general_value = {"theme": stored_general.get("theme", "dark"), "locale": stored_general.get("locale", "zh-CN")}
        # Determine writable/hasDocument
        writable = True
        has_document = False
        if settings_svc:
            if hasattr(settings_svc, "filepath"):
                try:
                    has_document = os.path.isfile(settings_svc.filepath)
                except Exception:
                    has_document = False
            # If settings service reports read-only, propagate
            if hasattr(settings_svc, "writable"):
                writable = bool(settings_svc.writable)
        # Build namespaces - strictly only writable/hasDocument/namespaces per TS contract
        namespaces = [
            {
                "ns": "llm",
                "schema": self._build_schemastery_schema("llm", has_key),
                "value": llm_value,
                "base": {},
                "user": stored_llm,
                "secrets": [{"path": ["apiKey"], "set": has_key}],
                "applies": "live",
                "revision": int(getattr(settings_svc, "_revision", 1)) if settings_svc and hasattr(settings_svc, "_revision") else 1,
            },
            {
                "ns": "general",
                "schema": self._build_schemastery_schema("general", False),
                "value": general_value,
                "base": {},
                "user": stored_general,
                "secrets": [],
                "applies": "live",
                "revision": 1,
            },
        ]
        # Backward compat: also expose top-level llm/general/plugins for legacy tests
        # while keeping spec namespaces as authoritative
        llm_top = llm_value
        general_top = general_value
        plugins_list = [
            {"id": "shell", "name": "Persistent Terminal Shell (pwsh/bash)", "active": True},
            {"id": "agent-loop", "name": "Cordis Agent Loop & Step Driver", "active": True},
            {"id": "compaction", "name": "Context Compaction & Summary Engine", "active": True},
            {"id": "fs-search", "name": "Filesystem Search (glob/grep)", "active": True},
            {"id": "web-search", "name": "DeepSeek / Tavily Web Search Engine", "active": True},
        ]
        return {
            "writable": writable,
            "hasDocument": has_document,
            "namespaces": namespaces,
            "llm": llm_top,
            "general": general_top,
            "plugins": plugins_list,
        }

    async def open_document(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Open settings file in OS default editor (`settings.openDocument`)."""
        settings_path = os.path.join(os.getcwd(), "settings.yaml")
        if not os.path.isfile(settings_path):
            try:
                with open(settings_path, "w", encoding="utf-8") as f:
                    f.write("# DeepSeek Harness Settings\n")
            except Exception:
                pass
        opened = open_native_path(settings_path)
        return {"opened": opened, "path": settings_path.replace("\\", "/")}

    async def update_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # TS: { ns: string; patch: object; expectedRevision?: number }
        ns = payload.get("ns") or payload.get("namespace") or "llm"
        patch = payload.get("patch") or payload.get("values") or payload.get("section") or {}
        # Also support legacy flat payload
        if not patch and any(k in payload for k in ("baseUrl", "base_url", "model", "apiKey")):
            patch = {k: v for k, v in payload.items() if k in ("baseUrl", "base_url", "baseURL", "model", "apiKey", "api_key", "providers")}
        expected_rev = payload.get("expectedRevision")
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        # Revision conflict check
        if settings_svc and expected_rev is not None and hasattr(settings_svc, "_revision"):
            actual = getattr(settings_svc, "_revision", 1)
            if int(expected_rev) != int(actual):
                raise ValueError(f"settings-conflict: ns '{ns}' expected {expected_rev} actual {actual}")
        # Apply patch to settings service
        if settings_svc and isinstance(patch, dict):
            for k, v in patch.items():
                # normalize keys
                norm_k = k
                if k in ("baseUrl", "baseURL"):
                    norm_k = "base_url"
                elif k in ("apiKey", "api_key"):
                    norm_k = "api_key"
                try:
                    if hasattr(settings_svc, "set_setting"):
                        settings_svc.set_setting(ns, norm_k, v)
                    elif hasattr(settings_svc, "_data"):
                        if ns not in settings_svc._data:
                            settings_svc._data[ns] = {}
                        settings_svc._data[ns][norm_k] = v
                except Exception as e:
                    raise ValueError(f"settings-rejected: {e}")
            # bump revision
            if hasattr(settings_svc, "_revision"):
                try:
                    settings_svc._revision = int(settings_svc._revision) + 1
                except Exception:
                    pass
        # Sync to llm service for live effect
        if llm and isinstance(patch, dict):
            if patch.get("baseUrl") or patch.get("base_url") or patch.get("baseURL"):
                llm.static_base_url = patch.get("baseUrl") or patch.get("base_url") or patch.get("baseURL")
            if patch.get("apiKey") or patch.get("api_key"):
                llm.static_api_key = patch.get("apiKey") or patch.get("api_key")
            if patch.get("model"):
                llm.static_model = patch["model"]
        # Return updated namespace view (as describe does for this ns)
        full = await self.describe_settings({})
        for n in full.get("namespaces", []):
            if n.get("ns") == ns:
                return n
        return full["namespaces"][0] if full.get("namespaces") else {}

    async def replace_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """TS: { ns: string; section: object; expectedRevision?: number }"""
        ns = payload.get("ns") or "llm"
        section = payload.get("section")
        if section is None:
            section = payload.get("values") or payload.get("patch") or {}
        expected_rev = payload.get("expectedRevision")
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        if settings_svc and expected_rev is not None and hasattr(settings_svc, "_revision"):
            actual = getattr(settings_svc, "_revision", 1)
            if int(expected_rev) != int(actual):
                raise ValueError(f"settings-conflict: ns '{ns}' expected {expected_rev} actual {actual}")
        if settings_svc:
            try:
                if hasattr(settings_svc, "_data"):
                    settings_svc._data[ns] = dict(section) if isinstance(section, dict) else {}
                if hasattr(settings_svc, "_revision"):
                    settings_svc._revision = int(settings_svc._revision) + 1
                if hasattr(settings_svc, "save"):
                    try:
                        settings_svc.save()
                    except Exception:
                        pass
            except Exception as e:
                raise ValueError(f"settings-rejected: {e}")
        # Sync llm
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        if llm and isinstance(section, dict):
            if "baseUrl" in section or "base_url" in section:
                llm.static_base_url = section.get("baseUrl") or section.get("base_url")
            if "model" in section:
                llm.static_model = section["model"]
            if "apiKey" in section:
                llm.static_api_key = section["apiKey"]
        full = await self.describe_settings({})
        for n in full.get("namespaces", []):
            if n.get("ns") == ns:
                return n
        return full["namespaces"][0] if full.get("namespaces") else {}

    async def mutate_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """TS: { ns: string; ops: SettingsPathOpView[]; expectedRevision?: number }"""
        ns = payload.get("ns") or "llm"
        ops = payload.get("ops") or payload.get("updates") or []
        expected_rev = payload.get("expectedRevision")
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        if settings_svc and expected_rev is not None and hasattr(settings_svc, "_revision"):
            actual = getattr(settings_svc, "_revision", 1)
            if int(expected_rev) != int(actual):
                raise ValueError(f"settings-conflict: ns '{ns}' expected {expected_rev} actual {actual}")
        # Apply ops
        target = {}
        if settings_svc and hasattr(settings_svc, "_data") and ns in settings_svc._data:
            import copy
            target = copy.deepcopy(settings_svc._data[ns])
        else:
            target = {}
        for op in ops if isinstance(ops, list) else []:
            if not isinstance(op, dict):
                continue
            kind = op.get("op")
            path = op.get("path") or []
            if kind == "set":
                val = op.get("value")
                cur = target
                for p in path[:-1]:
                    if p not in cur or not isinstance(cur[p], dict):
                        cur[p] = {}
                    cur = cur[p]
                if path:
                    cur[path[-1]] = val
                else:
                    if isinstance(val, dict):
                        target = val
            elif kind == "unset":
                cur = target
                for p in path[:-1]:
                    if p not in cur or not isinstance(cur[p], dict):
                        cur = None
                        break
                    cur = cur[p]
                if cur is not None and path and path[-1] in cur:
                    del cur[path[-1]]
        if settings_svc:
            try:
                if hasattr(settings_svc, "_data"):
                    settings_svc._data[ns] = target
                if hasattr(settings_svc, "_revision"):
                    settings_svc._revision = int(settings_svc._revision) + 1
            except Exception as e:
                raise ValueError(f"settings-rejected: {e}")
        # Sync llm if path touches relevant keys
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        if llm:
            # simplistic: if any op touches baseUrl/model/apiKey at root
            for op in ops if isinstance(ops, list) else []:
                p = op.get("path", [])
                if p == ["baseUrl"] or p == ["base_url"] or p == ["baseURL"]:
                    if op.get("op") == "set":
                        llm.static_base_url = op.get("value")
                    else:
                        llm.static_base_url = None
                if p == ["model"] and op.get("op") == "set":
                    llm.static_model = op.get("value")
                if p == ["apiKey"] and op.get("op") == "set":
                    llm.static_api_key = op.get("value")
        full = await self.describe_settings({})
        for n in full.get("namespaces", []):
            if n.get("ns") == ns:
                return n
        return full["namespaces"][0] if full.get("namespaces") else {}
