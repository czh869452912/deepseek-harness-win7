"""
Settings Domain Handler (`@deepseek-ai/dsh-apiproxy/api/settings`).
1:1 with reference `api/settings.ts`.
"""

import os
from typing import Any, Dict, List
from dsh.host.apiproxy.native_path_opener import open_native_path


class SettingsDomainHandler:
    """Handler for settings.* RPC methods."""

    def __init__(self, ctx: Any):
        self.ctx = ctx

    def _build_schemastery_schema(self, ns: str, has_key: bool) -> Dict[str, Any]:
        if ns in ("llm", "llm-deepseek", "llm-openai"):
            model_item_schema = {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "contextWindow": {"type": "number"},
                    "maxTokens": {"type": "number"},
                },
            }
            return {
                "type": "object",
                "properties": {
                    "baseUrl": {"type": "string"},
                    "base_url": {"type": "string"},
                    "model": {"type": "string"},
                    "apiKey": {"type": "string", "role": "secret"},
                    "api_key": {"type": "string", "role": "secret"},
                    "apiKeyEnv": {"type": "string"},
                    "models": {
                        "type": "array",
                        "value": model_item_schema,
                    },
                    "providers": {
                        "type": "dict",
                        "value": {
                            "type": "object",
                            "properties": {
                                "baseUrl": {"type": "string"},
                                "base_url": {"type": "string"},
                                "api": {"type": "union", "list": [{"value": "openai"}, {"value": "anthropic"}]},
                                "apiKeyEnv": {"type": "string"},
                                "apiKey": {"type": "string", "role": "secret"},
                                "model": {"type": "string"},
                                "models": {
                                    "type": "array",
                                    "value": model_item_schema,
                                },
                            },
                        },
                    },
                },
            }
        if ns == "general":
            return {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "locale": {"type": "string"},
                },
            }
        return {"type": "object", "properties": {}}

    def _collect_namespaces(self):
        # Build namespace list from directory + known defaults, 1:1 with TS settings registry
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        nss = set(["llm", "general"])
        if llm and hasattr(llm, "list_configurable_providers"):
            try:
                for entry in llm.list_configurable_providers():
                    ns = entry.get("settingsNs")
                    if ns:
                        nss.add(ns)
            except Exception:
                pass
        # also add any ns present in stored data
        if settings_svc and hasattr(settings_svc, "_data"):
            for k in settings_svc._data.keys():
                if k != "_meta" and isinstance(k, str):
                    nss.add(k)
        # ensure llm-deepseek / llm-openai present for provider mapping
        nss.add("llm-deepseek")
        nss.add("llm-openai")
        return sorted(nss)

    async def describe_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        has_key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or (llm and getattr(llm, "static_api_key", None)))
        writable = True
        has_document = False
        if settings_svc:
            if hasattr(settings_svc, "filepath"):
                try:
                    has_document = os.path.isfile(settings_svc.filepath)
                except Exception:
                    has_document = False
            if hasattr(settings_svc, "writable"):
                writable = bool(settings_svc.writable)
        namespaces = []
        for ns in self._collect_namespaces():
            stored = {}
            base = {}
            if settings_svc and hasattr(settings_svc, "_data") and isinstance(settings_svc._data, dict):
                stored = settings_svc._data.get(ns, {}) if isinstance(settings_svc._data.get(ns), dict) else {}
                # base is empty in python port (no base layer), keep {}
            # value is stored with live fallback for llm baseUrl/model
            value = dict(stored)
            if ns in ("llm", "llm-deepseek"):
                if "baseUrl" not in value and "base_url" not in value:
                    try:
                        fallback = llm.resolve_base_url() if llm else "https://api.deepseek.com"
                        value["baseUrl"] = fallback
                    except Exception:
                        pass
                if "model" not in value:
                    try:
                        value["model"] = llm.resolve_model() if llm else "deepseek-chat"
                    except Exception:
                        pass
            if ns == "general":
                if "theme" not in value:
                    value["theme"] = "dark"
                if "locale" not in value:
                    value["locale"] = "zh-CN"
            # secrets: redact apiKey presence
            secrets = []
            if ns in ("llm", "llm-deepseek", "llm-openai"):
                # check if any apiKey set
                has_ns_key = bool(stored.get("apiKey") or stored.get("api_key") or has_key)
                if has_ns_key:
                    # prefer canonical path
                    if "apiKey" in stored or has_key:
                        secrets.append({"path": ["apiKey"], "set": True})
                    else:
                        secrets.append({"path": ["api_key"], "set": True})
            revision = 1
            if settings_svc and hasattr(settings_svc, "get_revision"):
                try:
                    revision = settings_svc.get_revision(ns)
                except Exception:
                    revision = int(getattr(settings_svc, "_revision", 1))
            elif settings_svc and hasattr(settings_svc, "_revisions"):
                revision = int(settings_svc._revisions.get(ns, getattr(settings_svc, "_revision", 1)))
            else:
                revision = int(getattr(settings_svc, "_revision", 1)) if settings_svc else 1
            namespaces.append({
                "ns": ns,
                "schema": self._build_schemastery_schema(ns, has_key),
                "value": value,
                "base": base,
                "user": dict(stored),
                "secrets": secrets,
                "applies": "live",
                "revision": revision,
            })
        # Backward compat top-level for legacy tests
        # find llm/general value
        llm_top = next((n["value"] for n in namespaces if n["ns"] == "llm"), {})
        general_top = next((n["value"] for n in namespaces if n["ns"] == "general"), {})
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
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        settings_path = None
        if settings_svc and hasattr(settings_svc, "filepath"):
            settings_path = settings_svc.filepath
        else:
            settings_path = os.path.join(os.getcwd(), "settings.yaml")
        if not os.path.isfile(settings_path):
            try:
                os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
                with open(settings_path, "w", encoding="utf-8") as f:
                    f.write("# DeepSeek Harness Settings\n")
            except Exception:
                pass
        opened = open_native_path(settings_path)
        if opened:
            return {"opened": True}
        return {"opened": False, "path": settings_path.replace("\\", "/")}

    def _check_conflict(self, ns: str, expected_rev):
        if expected_rev is None:
            return
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        if not settings_svc:
            return
        actual = None
        if hasattr(settings_svc, "get_revision"):
            actual = settings_svc.get_revision(ns)
        elif hasattr(settings_svc, "_revisions"):
            actual = settings_svc._revisions.get(ns, getattr(settings_svc, "_revision", 1))
        else:
            actual = getattr(settings_svc, "_revision", 1)
        if int(expected_rev) != int(actual):
            # 1:1 error code settings-conflict with details; proxy will extract code
            raise ValueError("settings-conflict: ns '{}' expected {} actual {}".format(ns, expected_rev, actual))

    async def update_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ns = payload.get("ns") or payload.get("namespace") or "llm"
        patch = payload.get("patch") or payload.get("values") or payload.get("section") or {}
        if not patch and any(k in payload for k in ("baseUrl", "base_url", "model", "apiKey", "providers")):
            patch = {k: v for k, v in payload.items() if k in ("baseUrl", "base_url", "baseURL", "model", "apiKey", "api_key", "providers")}
        expected_rev = payload.get("expectedRevision")
        self._check_conflict(ns, expected_rev)
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        if settings_svc and isinstance(patch, dict):
            for k, v in patch.items():
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
                    raise ValueError("settings-rejected: {}".format(e))
        if llm and isinstance(patch, dict):
            if patch.get("baseUrl") or patch.get("base_url") or patch.get("baseURL"):
                llm.static_base_url = patch.get("baseUrl") or patch.get("base_url") or patch.get("baseURL")
            if patch.get("apiKey") or patch.get("api_key"):
                llm.static_api_key = patch.get("apiKey") or patch.get("api_key")
            if patch.get("model"):
                llm.static_model = patch["model"]
            # handle providers nested
            if isinstance(patch.get("providers"), dict):
                if settings_svc and hasattr(settings_svc, "_data"):
                    settings_svc._data[ns] = settings_svc._data.get(ns, {})
                    settings_svc._data[ns]["providers"] = patch["providers"]
                    if hasattr(settings_svc, "save"):
                        settings_svc.save()
        full = await self.describe_settings({})
        for n in full.get("namespaces", []):
            if n.get("ns") == ns:
                return n
        return full["namespaces"][0] if full.get("namespaces") else {}

    async def replace_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ns = payload.get("ns") or "llm"
        section = payload.get("section")
        if section is None:
            section = payload.get("values") or payload.get("patch") or {}
        expected_rev = payload.get("expectedRevision")
        self._check_conflict(ns, expected_rev)
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        if settings_svc:
            try:
                if hasattr(settings_svc, "_data"):
                    settings_svc._data[ns] = dict(section) if isinstance(section, dict) else {}
                if hasattr(settings_svc, "bump_revision"):
                    settings_svc.bump_revision(ns)
                elif hasattr(settings_svc, "_revisions"):
                    settings_svc._revisions[ns] = int(settings_svc._revisions.get(ns, 1)) + 1
                if hasattr(settings_svc, "_revision"):
                    settings_svc._revision = int(settings_svc._revision) + 1
                if hasattr(settings_svc, "save"):
                    try:
                        settings_svc.save()
                    except Exception:
                        pass
            except Exception as e:
                raise ValueError("settings-rejected: {}".format(e))
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        if llm and isinstance(section, dict):
            if "baseUrl" in section or "base_url" in section:
                llm.static_base_url = section.get("baseUrl") or section.get("base_url")
            if "model" in section:
                llm.static_model = section["model"]
            if "apiKey" in section or "api_key" in section:
                llm.static_api_key = section.get("apiKey") or section.get("api_key")
        full = await self.describe_settings({})
        for n in full.get("namespaces", []):
            if n.get("ns") == ns:
                return n
        return full["namespaces"][0] if full.get("namespaces") else {}

    async def mutate_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ns = payload.get("ns") or "llm"
        ops = payload.get("ops") or payload.get("updates") or []
        expected_rev = payload.get("expectedRevision")
        self._check_conflict(ns, expected_rev)
        settings_svc = self.ctx.get("settings") if hasattr(self.ctx, "get") else None
        import copy
        target = {}
        if settings_svc and hasattr(settings_svc, "_data") and ns in settings_svc._data:
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
                if hasattr(settings_svc, "bump_revision"):
                    settings_svc.bump_revision(ns)
                elif hasattr(settings_svc, "_revisions"):
                    settings_svc._revisions[ns] = int(settings_svc._revisions.get(ns, 1)) + 1
                if hasattr(settings_svc, "_revision"):
                    settings_svc._revision = int(settings_svc._revision) + 1
                if hasattr(settings_svc, "save"):
                    settings_svc.save()
            except Exception as e:
                raise ValueError("settings-rejected: {}".format(e))
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        if llm:
            for op in ops if isinstance(ops, list) else []:
                p = op.get("path", [])
                # root keys
                if p == ["baseUrl"] or p == ["base_url"] or p == ["baseURL"]:
                    if op.get("op") == "set":
                        llm.static_base_url = op.get("value")
                    else:
                        llm.static_base_url = None
                if p == ["model"] and op.get("op") == "set":
                    llm.static_model = op.get("value")
                if p == ["apiKey"] or p == ["api_key"]:
                    if op.get("op") == "set":
                        llm.static_api_key = op.get("value")
                    else:
                        llm.static_api_key = None
                # provider nested: ["providers","openai","baseUrl"]
                if len(p) == 3 and p[0] == "providers":
                    # sync to static not needed per-provider; settings file holds it
                    pass
        full = await self.describe_settings({})
        for n in full.get("namespaces", []):
            if n.get("ns") == ns:
                return n
        return full["namespaces"][0] if full.get("namespaces") else {}
