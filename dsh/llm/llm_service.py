import json
import copy
import math
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.typert.remote import Remote, bind_typert_remote, TypertRemoteFailure


class LlmError(RuntimeError):
    def __init__(self, message, code, status=None, providerRetryAfterMs=None, requestId=None):
        if not isinstance(message, str) or not message:
            raise ValueError("LlmError message must be a non-empty string")
        if not isinstance(code, str) or not code:
            raise ValueError("LlmError code must be a non-empty string")
        if status is not None:
            if isinstance(status, bool) or not isinstance(status, int) or status < 100 or status > 599:
                raise ValueError("LlmError status must be an integer from 100 through 599")
        if providerRetryAfterMs is not None:
            if not isinstance(providerRetryAfterMs, (int, float)) or isinstance(providerRetryAfterMs, bool) or providerRetryAfterMs <= 0 or math.isnan(providerRetryAfterMs) or math.isinf(providerRetryAfterMs):
                raise ValueError("LlmError providerRetryAfterMs must be a positive finite number")
        if requestId is not None:
            if not isinstance(requestId, str) or not requestId:
                raise ValueError("LlmError requestId must be a non-empty string")
        super(LlmError, self).__init__(f"[{code}] {message}")
        self.code = code
        self.status = status
        self.providerRetryAfterMs = providerRetryAfterMs
        self.requestId = requestId
        self.failure = {
            "message": message,
            "code": code,
        }
        if status is not None:
            self.failure["status"] = status
        if providerRetryAfterMs is not None:
            self.failure["providerRetryAfterMs"] = providerRetryAfterMs
        if requestId is not None:
            self.failure["requestId"] = requestId


LEGAL_API_KEY_PATTERN = r"^[\x21-\x7E]+$"


def normalize_api_key(raw: str) -> Dict[str, Any]:
    if not isinstance(raw, str):
        return {"ok": False, "reason": "empty"}
    value = raw.strip()
    if len(value) == 0:
        return {"ok": False, "reason": "empty"}
    import re
    if not re.match(LEGAL_API_KEY_PATTERN, value):
        return {"ok": False, "reason": "illegalCharacters"}
    return {"ok": True, "value": value}


def assert_usable_api_key(raw: str, pkg: str, ref: str) -> str:
    checked = normalize_api_key(raw)
    if checked["ok"]:
        return checked["value"]
    if checked["reason"] == "empty":
        msg = f"{pkg}: the API key resolved from {ref} is blank; set {ref} to the raw key (the web Models page writes it) or export it in the launching environment"
    else:
        msg = f"{pkg}: the API key resolved from {ref} contains characters no HTTP header can carry; set {ref} to the raw key alone (the web Models page writes it)"
    raise LlmError(msg, "INVALID_CREDENTIAL")


class LLMService:
    """
    LLM Service registered at `ctx.llm`.
    1:1 with reference `packages/llm/llm/src/index.ts` LlmRuntime + OpenAI-compatible defaults.
    Provides adapter registry, configurable-provider directory, model discovery,
    layered configuration resolution, and streaming waterfall hook.
    """

    def __init__(
        self,
        ctx=None,
        api_key=None,
        base_url=None,
        search_base_url=None,
        model=None,
        api_key_env="DEEPSEEK_API_KEY"
    ):
        self.ctx = ctx
        self.typertRemote = bind_typert_remote(self, "llm")
        self.static_api_key = api_key if (api_key and api_key.strip()) else None
        self.static_base_url = base_url if (base_url and base_url.strip()) else None
        self.static_search_base_url = search_base_url if (search_base_url and search_base_url.strip()) else None
        self.static_model = model if (model and model.strip()) else None
        self.api_key_env = api_key_env
        # Registry (1:1 with LlmRuntime)
        self._adapters = {}  # provider -> {adapter, provider:{id,name}, retryPolicy}
        self._directory = {}  # provider -> {provider, displayName, settingsNs, settingsPath, declared?}
        self._discoveries = {}  # settingsNs -> fn
        # fallback default models
        self._default_catalog = [
            {"provider": "deepseek-official", "id": "deepseek-chat", "name": "DeepSeek Chat"},
            {"provider": "deepseek-official", "id": "deepseek-reasoner", "name": "DeepSeek Reasoner"},
        ]

    # ---- config resolution (1:1 fallback chain) ----
    def resolve_api_key(self, provider=None):
        if self.static_api_key:
            return assert_usable_api_key(self.static_api_key, "llm", self.api_key_env)

        if provider:
            prov_env_name = "{}_API_KEY".format(provider.upper().replace("-", "_"))
            env_key = os.environ.get(prov_env_name)
            if env_key:
                return assert_usable_api_key(env_key, "llm", prov_env_name)

        env_key = (
            os.environ.get(self.api_key_env)
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        if env_key:
            return assert_usable_api_key(env_key, "llm", self.api_key_env)

        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("credentials"):
            creds = self.ctx.get("credentials")
            try:
                refs_to_try = []
                if provider:
                    refs_to_try.append("{}_API_KEY".format(provider.upper().replace("-", "_")))
                refs_to_try.extend([self.api_key_env, "DEEPSEEK_API_KEY", "OPENAI_API_KEY"])
                for ref in refs_to_try:
                    val = creds.resolve(ref) if hasattr(creds, "resolve") else None
                    if val:
                        if isinstance(val, dict):
                            v = val.get("value")
                            if v:
                                return assert_usable_api_key(v, "llm", ref)
                        elif isinstance(val, str) and val.strip():
                            return assert_usable_api_key(val, "llm", ref)
            except Exception:
                pass

        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            for ns in ("llm", "llm-deepseek", "llm-openai"):
                if provider and hasattr(settings, "get_setting"):
                    providers_dict = settings.get_setting(ns, "providers")
                    if isinstance(providers_dict, dict) and provider in providers_dict:
                        p_cfg = providers_dict[provider]
                        if isinstance(p_cfg, dict):
                            v = p_cfg.get("apiKey") or p_cfg.get("api_key")
                            if v and isinstance(v, str) and v.strip():
                                return assert_usable_api_key(v, "llm", "{}.providers.{}.apiKey".format(ns, provider))
                            ref = p_cfg.get("apiKeyEnv")
                            if ref and isinstance(ref, str) and ref.strip():
                                env_v = os.environ.get(ref.strip())
                                if env_v:
                                    return assert_usable_api_key(env_v, "llm", ref)
                if hasattr(settings, "get_setting"):
                    for key in ("api_key", "apiKey"):
                        v = settings.get_setting(ns, key)
                        if v and isinstance(v, str) and v.strip():
                            return assert_usable_api_key(v, "llm", "{}.{}".format(ns, key))

        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("launch_environment"):
            launch_env = self.ctx.get("launch_environment")
            entry = (
                launch_env.get_from(self.api_key_env, ["project-env", "user-env"])
                or launch_env.get_from("DEEPSEEK_API_KEY", ["project-env", "user-env"])
                or launch_env.get_from("OPENAI_API_KEY", ["project-env", "user-env"])
            )
            if entry and entry.value:
                return assert_usable_api_key(entry.value, "llm", self.api_key_env)

        ref_name = "{}_API_KEY".format(provider.upper().replace("-", "_")) if provider else self.api_key_env
        raise LlmError(
            "LLM API Key missing for '{}'. Export DEEPSEEK_API_KEY or configure the credentials service.".format(ref_name),
            "MISSING_CREDENTIAL"
        )

    def resolve_base_url(self, provider=None):
        if self.static_base_url:
            return self.static_base_url.rstrip("/")

        if provider:
            prov_env = "{}_BASE_URL".format(provider.upper().replace("-", "_"))
            env_url = os.environ.get(prov_env)
            if env_url:
                return env_url.rstrip("/")

        env_url = (
            os.environ.get("DEEPSEEK_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        )
        if env_url:
            return env_url.rstrip("/")

        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            for ns in ("llm", "llm-deepseek", "llm-openai"):
                if provider and hasattr(settings, "get_setting"):
                    providers_dict = settings.get_setting(ns, "providers")
                    if isinstance(providers_dict, dict) and provider in providers_dict:
                        p_cfg = providers_dict[provider]
                        if isinstance(p_cfg, dict):
                            v = p_cfg.get("baseUrl") or p_cfg.get("base_url") or p_cfg.get("baseURL")
                            if v and isinstance(v, str) and v.strip():
                                return str(v).rstrip("/")
                if hasattr(settings, "get_setting"):
                    for key in ("base_url", "baseURL", "baseUrl"):
                        v = settings.get_setting(ns, key)
                        if v and isinstance(v, str) and v.strip():
                            return str(v).rstrip("/")

        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("launch_environment"):
            launch_env = self.ctx.get("launch_environment")
            entry = (
                launch_env.get_from("DEEPSEEK_BASE_URL", ["project-env", "user-env"])
                or launch_env.get_from("OPENAI_BASE_URL", ["project-env", "user-env"])
            )
            if entry and entry.value:
                return entry.value.rstrip("/")

        return "https://api.deepseek.com"

    def resolve_search_base_url(self, provider=None):
        if self.static_search_base_url:
            return self.static_search_base_url.rstrip("/")
        env_url = os.environ.get("DEEPSEEK_SEARCH_BASE_URL")
        if env_url:
            return env_url.rstrip("/")
        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            for ns in ("llm", "llm-deepseek", "llm-openai"):
                if hasattr(settings, "get_setting"):
                    for key in ("search_base_url", "searchBaseURL"):
                        v = settings.get_setting(ns, key)
                        if v and isinstance(v, str) and v.strip():
                            return str(v).rstrip("/")
        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("launch_environment"):
            launch_env = self.ctx.get("launch_environment")
            entry = launch_env.get_from("DEEPSEEK_SEARCH_BASE_URL", ["project-env", "user-env"])
            if entry and entry.value:
                return entry.value.rstrip("/")
        return self.resolve_base_url(provider)

    def resolve_model(self, req_model=None, provider=None):
        if req_model:
            return req_model
        if self.static_model:
            return self.static_model

        if provider:
            prov_env = "{}_MODEL".format(provider.upper().replace("-", "_"))
            env_model = os.environ.get(prov_env)
            if env_model:
                return env_model

        env_model = (
            os.environ.get("DEEPSEEK_MODEL")
            or os.environ.get("OPENAI_MODEL")
        )
        if env_model:
            return env_model

        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            for ns in ("llm", "llm-deepseek", "llm-openai"):
                if provider and hasattr(settings, "get_setting"):
                    providers_dict = settings.get_setting(ns, "providers")
                    if isinstance(providers_dict, dict) and provider in providers_dict:
                        p_cfg = providers_dict[provider]
                        if isinstance(p_cfg, dict):
                            v = p_cfg.get("model") or p_cfg.get("model_name") or p_cfg.get("modelName")
                            if v and isinstance(v, str) and v.strip():
                                return str(v).strip()
                if hasattr(settings, "get_setting"):
                    for key in ("model", "model_name", "modelName"):
                        v = settings.get_setting(ns, key)
                        if v and isinstance(v, str) and v.strip():
                            return str(v).strip()

        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("launch_environment"):
            launch_env = self.ctx.get("launch_environment")
            entry = (
                launch_env.get_from("DEEPSEEK_MODEL", ["project-env", "user-env"])
                or launch_env.get_from("OPENAI_MODEL", ["project-env", "user-env"])
            )
            if entry and entry.value:
                return entry.value

        return "deepseek-chat"

    # ---- adapter/directory/discovery registry (1:1) ----
    def _emit_adapters_updated(self):
        if self.ctx is None:
            return
        try:
            # emit is fire-and-forget, contain per-listener failures like TS
            # use ctx.emit which already contains; also try ctx.events.dispatch emit manually if needed
            self.ctx.emit("llm/adapters-updated")
        except Exception:
            pass

    def register_adapter(self, providers, adapter):
        if not providers:
            raise LlmError("an adapter must register at least one provider", "INVALID_ADAPTER")
        # validate
        unique = set()
        regs = []
        owned_set = set()
        for p in providers:
            if not p:
                raise LlmError("adapter provider names must be non-empty", "INVALID_ADAPTER")
            if p in unique or (p in self._adapters):
                raise LlmError('an adapter for provider "{}" is already registered'.format(p), "DUPLICATE_ADAPTER")
            info = None
            try:
                info_fn = getattr(adapter, "provider_info", getattr(adapter, "providerInfo", None))
                info = info_fn(p) if info_fn else {"id": p, "name": p}
            except Exception:
                info = {"id": p, "name": p}
            if not isinstance(info, dict) or info.get("id") != p or not info.get("name"):
                raise LlmError('adapter metadata for provider "{}" must preserve its id and have a non-empty name'.format(p), "INVALID_ADAPTER")
            unique.add(p)
            retry = None
            retry_fn = getattr(adapter, "provider_retry_policy", getattr(adapter, "providerRetryPolicy", None))
            retry = copy.deepcopy(retry_fn(p)) if retry_fn else None
            regs.append({"adapter": adapter, "provider": {"id": info["id"], "name": info["name"]}, "retryPolicy": retry})
        for r in regs:
            self._adapters[r["provider"]["id"]] = r
        self._emit_adapters_updated()
        released = {"v": False}
        owned = set(providers)

        def dispose():
            if released["v"]:
                return
            released["v"] = True
            for pp in list(owned):
                self._adapters.pop(pp, None)
            owned.clear()
            self._emit_adapters_updated()

        def replace(next_providers):
            if released["v"]:
                raise LlmError("a disposed adapter registration cannot replace its routes", "REGISTRATION_DISPOSED")
            if not isinstance(next_providers, list):
                next_providers = list(next_providers)
            # validate before mutating
            uniq2 = set()
            regs2 = []
            for p in next_providers:
                if not p:
                    raise LlmError("adapter provider names must be non-empty", "INVALID_ADAPTER")
                if p in uniq2 or (p in self._adapters and p not in owned):
                    raise LlmError('an adapter for provider "{}" is already registered'.format(p), "DUPLICATE_ADAPTER")
                info_fn = getattr(adapter, "provider_info", getattr(adapter, "providerInfo", None))
                info = info_fn(p) if info_fn else {"id": p, "name": p}
                if not isinstance(info, dict) or info.get("id") != p or not info.get("name"):
                    raise LlmError('adapter metadata for provider "{}" must preserve its id and have a non-empty name'.format(p), "INVALID_ADAPTER")
                uniq2.add(p)
                retry_fn = getattr(adapter, "provider_retry_policy", getattr(adapter, "providerRetryPolicy", None))
                retry = copy.deepcopy(retry_fn(p)) if retry_fn else None
                regs2.append({"adapter": adapter, "provider": {"id": info["id"], "name": info["name"]}, "retryPolicy": retry})
            for pp in list(owned):
                self._adapters.pop(pp, None)
            owned.clear()
            for r in regs2:
                self._adapters[r["provider"]["id"]] = r
                owned.add(r["provider"]["id"])
            self._emit_adapters_updated()

        # attach replace as attribute on dispose fn to mimic TS handle
        dispose.replace = replace  # type: ignore
        # also register effect disposal if ctx available
        if self.ctx and hasattr(self.ctx, "effect"):
            try:
                # effect that keeps registration alive with fiber; on dispose, call dispose
                def _effect_gen():
                    yield dispose
                self.ctx.effect(_effect_gen, "llm.registerAdapter()")
            except Exception:
                pass
        return dispose

    def register_configurable_providers(self, entries):
        if not entries:
            raise LlmError("a configurable-provider registration must declare at least one provider", "INVALID_DIRECTORY")
        # full validation before mutation
        detached = []
        for e in entries:
            provider = e.get("provider", "")
            display = e.get("displayName", "")
            ns = e.get("settingsNs", "")
            path = e.get("settingsPath", [])
            if not provider or not display or not ns:
                raise LlmError("configurable providers need a non-empty provider, displayName, and settingsNs", "INVALID_DIRECTORY")
            if any(not seg for seg in path):
                raise LlmError('configurable provider "{}" has an empty settingsPath segment'.format(provider), "INVALID_DIRECTORY")
            if provider in self._directory or any(d["provider"] == provider for d in detached):
                raise LlmError('configurable provider "{}" is already declared'.format(provider), "DUPLICATE_DIRECTORY")
            detached.append({"provider": provider, "displayName": display, "settingsNs": ns, "settingsPath": list(path), "declared": e.get("declared")})
        for d in detached:
            self._directory[d["provider"]] = d
        self._emit_adapters_updated()
        held = list(detached)
        disposed = {"v": False}

        def dispose():
            if disposed["v"]:
                return
            disposed["v"] = True
            for d in held:
                self._directory.pop(d["provider"], None)
            held.clear()
            self._emit_adapters_updated()

        def replace(next_entries):
            if disposed["v"]:
                raise LlmError("this configurable-provider registration was disposed", "REGISTRATION_DISPOSED")
            # validate full
            nd = []
            own = set(x["provider"] for x in held)
            for e in (next_entries or []):
                provider = e.get("provider", "")
                display = e.get("displayName", "")
                ns = e.get("settingsNs", "")
                path = e.get("settingsPath", [])
                if not provider or not display or not ns:
                    raise LlmError("configurable providers need a non-empty provider, displayName, and settingsNs", "INVALID_DIRECTORY")
                if any(not seg for seg in path):
                    raise LlmError('configurable provider "{}" has an empty settingsPath segment'.format(provider), "INVALID_DIRECTORY")
                if (provider in self._directory and provider not in own) or any(x["provider"] == provider for x in nd):
                    raise LlmError('configurable provider "{}" is already declared'.format(provider), "DUPLICATE_DIRECTORY")
                nd.append({"provider": provider, "displayName": display, "settingsNs": ns, "settingsPath": list(path), "declared": e.get("declared")})
            for d in held:
                self._directory.pop(d["provider"], None)
            held.clear()
            for d in nd:
                self._directory[d["provider"]] = d
                held.append(d)
            self._emit_adapters_updated()

        dispose.replace = replace  # type: ignore
        if self.ctx and hasattr(self.ctx, "effect"):
            try:
                def _eff():
                    yield dispose
                self.ctx.effect(_eff, "llm.registerConfigurableProviders()")
            except Exception:
                pass
        return dispose

    def register_model_discovery(self, settings_ns, discover):
        if not settings_ns:
            raise LlmError("model discovery needs a non-empty settings namespace", "INVALID_DISCOVERY")
        if settings_ns in self._discoveries:
            raise LlmError('model discovery for "{}" is already registered'.format(settings_ns), "DUPLICATE_DISCOVERY")
        self._discoveries[settings_ns] = discover
        def dispose():
            self._discoveries.pop(settings_ns, None)
        if self.ctx and hasattr(self.ctx, "effect"):
            try:
                def _eff():
                    yield dispose
                self.ctx.effect(_eff, "llm.registerModelDiscovery()")
            except Exception:
                pass
        return dispose

    def list_providers(self):
        # detached copies in registration order
        return [dict(v["provider"]) for v in self._adapters.values()]

    def list_configurable_providers(self):
        return [dict(provider=v["provider"], displayName=v["displayName"], settingsNs=v["settingsNs"], settingsPath=list(v["settingsPath"]), **({"declared": v["declared"]} if "declared" in v and v["declared"] is not None else {})) for v in self._directory.values()]

    async def discover_models(self, settings_ns, options, signal=None):
        discover = self._discoveries.get(settings_ns)
        if discover is None:
            raise LlmError('no model discovery is registered for "{}"'.format(settings_ns), "NO_DISCOVERY")
        provider = options.get("provider") if isinstance(options, dict) else None
        base_url = options.get("baseURL") or options.get("base_url") if isinstance(options, dict) else None
        if not (provider and str(provider).strip()) and not (base_url and str(base_url).strip()):
            raise LlmError("model discovery needs a provider route or a baseURL", "INVALID_DISCOVERY")
        # call discovery
        import inspect as _ins
        if signal is not None:
            try:
                _ins.signature(discover).bind(options, signal)
            except (ValueError, TypeError):
                res = discover(options)
            else:
                res = discover(options, signal)
        else:
            res = discover(options)
        if _ins.isawaitable(res):
            res = await res
        seen = set()
        models = []
        for m in (res or []):
            mid = m.get("id") if isinstance(m, dict) else None
            if not isinstance(mid, str) or not mid or mid in seen:
                continue
            seen.add(mid)
            out = {"id": mid}
            if isinstance(m.get("name"), str) and m.get("name"):
                out["name"] = m["name"]
            if m.get("contextWindow") is not None:
                out["contextWindow"] = m["contextWindow"]
            if m.get("maxTokens") is not None:
                out["maxTokens"] = m["maxTokens"]
            models.append(out)
        return models

    def _get_adapter_entry(self, provider):
        e = self._adapters.get(provider)
        if not e:
            # fallback: if no adapter registered, use static behavior as pseudo-adapter
            if provider in ("deepseek", "openai", "deepseek-official"):
                return None
            raise LlmError('no adapter registered for provider "{}"'.format(provider), "NO_ADAPTER")
        return e

    async def list_models(self, provider_id="deepseek"):
        # try adapter
        entry = self._adapters.get(provider_id)
        if entry:
            adapter = entry["adapter"]
            fn = getattr(adapter, "list_models", getattr(adapter, "listModels", None))
            if fn:
                try:
                    import inspect as _ins
                    res = fn(provider_id)
                    if _ins.isawaitable(res):
                        res = await res
                    # validate per spec
                    seen = set()
                    out = []
                    for m in (res or []):
                        if not isinstance(m, dict) or m.get("provider") != provider_id or not m.get("id") or not m.get("name") or m["id"] in seen:
                            raise LlmError('adapter returned invalid or duplicate model metadata for provider "{}"'.format(provider_id), "INVALID_CATALOG")
                        seen.add(m["id"])
                        item = {"id": m["id"], "name": m["name"]}
                        if m.get("description"):
                            item["description"] = m["description"]
                        if m.get("inputModalities"):
                            item["inputModalities"] = list(m["inputModalities"])
                        if m.get("reasoning"):
                            item["reasoning"] = m["reasoning"]
                        out.append(item)
                    return out
                except LlmError:
                    raise
                except Exception as e:
                    raise LlmError(str(e), "INVALID_CATALOG")

        # Check settings for custom models configured under provider
        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            for ns in ("llm", "llm-deepseek", "llm-openai"):
                if hasattr(settings, "get_setting"):
                    providers_dict = settings.get_setting(ns, "providers")
                    if isinstance(providers_dict, dict) and provider_id in providers_dict:
                        p_cfg = providers_dict[provider_id]
                        if isinstance(p_cfg, dict) and "models" in p_cfg and isinstance(p_cfg["models"], list):
                            out = []
                            for m in p_cfg["models"]:
                                if isinstance(m, dict) and m.get("id"):
                                    out.append({
                                        "id": m["id"],
                                        "name": m.get("name") or m["id"],
                                        **({"description": m["description"]} if m.get("description") else {})
                                    })
                            if out:
                                return out
                    # Also check namespace-level models
                    models_list = settings.get_setting(ns, "models")
                    if isinstance(models_list, list) and models_list:
                        out = []
                        for m in models_list:
                            if isinstance(m, dict) and m.get("id"):
                                out.append({
                                    "id": m["id"],
                                    "name": m.get("name") or m["id"],
                                    **({"description": m["description"]} if m.get("description") else {})
                                })
                        if out:
                            return out

        # fallback hardcoded catalog mirroring original
        if provider_id in ("deepseek", "deepseek-official"):
            return [
                {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)", "description": "High efficiency general reasoning"},
                {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)", "description": "Deep reasoning with explicit chain-of-thought"}
            ]
        if provider_id == "openai":
            return [
                {"id": "gpt-4o", "name": "GPT-4o"},
                {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            ]
        return []

    async def resolve_model_info(self, provider_id, model_id, signal=None):
        # try adapter
        entry = self._adapters.get(provider_id)
        if entry:
            adapter = entry["adapter"]
            fn = getattr(adapter, "resolve_model", getattr(adapter, "resolveModel", None))
            if fn:
                try:
                    import inspect as _ins
                    import inspect
                    sig = inspect.signature(fn)
                    if len(sig.parameters) >= 3 or "signal" in sig.parameters:
                        res = fn(provider_id, model_id, signal)
                    else:
                        res = fn(provider_id, model_id)
                    if _ins.isawaitable(res):
                        res = await res
                    if isinstance(res, dict):
                        p = res.get("provider")
                        m_id = res.get("id")
                        name = res.get("name")
                        if p != provider_id or m_id != model_id or not isinstance(name, str) or not name:
                            raise LlmError(f'adapter returned invalid exact model metadata for provider "{provider_id}" model "{model_id}"', "INVALID_MODEL_INFO")
                        return res
                except LlmError:
                    raise
                except Exception as e:
                    raise LlmError(str(e), "INVALID_MODEL_INFO")
        return {"provider": provider_id, "id": model_id, "name": model_id}

    def retry_policy(self, provider):
        return copy.deepcopy(self._adapters.get(provider, {}).get("retryPolicy"))

    def image_request_pricing(self, provider, model):
        adapter = self._adapters.get(provider, {}).get("adapter")
        method = getattr(adapter, "image_request_pricing", None) or getattr(adapter, "imageRequestPricing", None)
        return method(provider, model) if method else None

    imageRequestPricing = image_request_pricing

    async def stream(self, options):
        """Auxiliary plugin calls use the same route and stream hooks as agents."""
        from dsh.llm.stream_bridge import iter_chunks
        prepared = await self.prepare_adapter_call(options["provider"], options["model"], options.get("signal"))
        def open_stream(*_args):
            if prepared:
                return prepared["stream"](options)
            return self.chat_completion_stream(options["messages"], tools=options.get("tools"),
                model=options["model"], provider=options["provider"], system=options.get("system"), request=options)
        stream = await self.ctx.waterfall("llm/stream", options, open_stream) if self.ctx else open_stream()
        reader = iter_chunks(stream)
        try:
            async for chunk in reader:
                yield chunk
        finally:
            await reader.aclose()

    async def prepare_adapter_call(self, provider, model, signal=None):
        adapter = self._adapters.get(provider, {}).get("adapter")
        method = getattr(adapter, "prepare_call", None)
        if not callable(method):
            return None
        prepared = await method(provider, model, signal)
        if "image" not in prepared["model"].get("inputModalities", []):
            from dsh.llm.image_content import project_text_only
            original_stream = prepared["stream"]
            def stream(request):
                return original_stream(dict(request, messages=project_text_only(request["messages"])))
            prepared = dict(prepared, stream=stream)
        return prepared

    async def prepare_call(self, config: Dict[str, Any], signal: Any = None) -> Dict[str, Any]:
        provider_id = config.get("provider") or getattr(self, "provider", "openai")
        model_id = config.get("model") or getattr(self, "model", "deepseek-chat")
        prepared = await self.prepare_adapter_call(provider_id, model_id, signal)
        model_info = prepared["model"] if prepared else await self.resolve_model_info(provider_id, model_id, signal=signal)

        cfg_max_tokens = config.get("maxTokens") if "maxTokens" in config else config.get("max_tokens")
        cfg_reasoning_effort = config.get("reasoningEffort") if "reasoningEffort" in config else config.get("reasoning_effort")

        defaults = {
            "maxTokens": cfg_max_tokens is None,
            "reasoningEffort": cfg_reasoning_effort is None,
        }

        max_tokens = cfg_max_tokens if cfg_max_tokens is not None else model_info.get("defaultMaxTokens")

        reasoning_effort = cfg_reasoning_effort
        reasoning_meta = model_info.get("reasoning")
        if isinstance(reasoning_meta, dict):
            if reasoning_effort is None:
                reasoning_effort = reasoning_meta.get("defaultEffort")
            allowed_efforts = reasoning_meta.get("efforts")
            if reasoning_effort is not None and isinstance(allowed_efforts, list):
                if reasoning_effort not in allowed_efforts:
                    raise LlmError(
                        f'Model "{model_id}" does not support reasoning effort "{reasoning_effort}"; allowed: {allowed_efforts}',
                        "UNSUPPORTED_REASONING_EFFORT",
                    )
        elif reasoning_effort is not None:
            raise LlmError(
                f'Model "{model_id}" does not declare reasoning capabilities but requested effort "{reasoning_effort}"',
                "UNSUPPORTED_REASONING_EFFORT",
            )

        return {
            "provider": provider_id,
            "model": model_info,
            "maxTokens": max_tokens,
            "reasoningEffort": reasoning_effort,
            "adapterDefaults": defaults,
            **({"stream": prepared["stream"], "retryPolicy": prepared.get("retryPolicy")} if prepared else {}),
        }

    async def prepareCall(self, config: Dict[str, Any], signal: Any = None) -> Dict[str, Any]:
        return await self.prepare_call(config, signal=signal)

    # backward compat alias
    def list_configurable_providers_sync(self):
        return self.list_configurable_providers()

    def chat_completion(
        self,
        messages,
        tools=None,
        model=None,
        temperature=0.0,
        provider=None,
        system=None,
        **kwargs,
    ):
        if provider and provider in self._adapters:
            adapter = self._adapters[provider]["adapter"]
            fn = getattr(adapter, "chat_completion", getattr(adapter, "complete", None))
            if fn and callable(fn):
                return fn(messages=messages, tools=tools, model=model, temperature=temperature, provider=provider, system=system)

        api_key = self.resolve_api_key(provider)
        base_url = self.resolve_base_url(provider)
        selected_model = self.resolve_model(model, provider)
        url = "{}/chat/completions".format(base_url)
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(api_key)
        }
        formatted_messages = list(messages)
        if system and not any(isinstance(m, dict) and m.get("role") == "system" for m in formatted_messages):
            formatted_messages = [{"role": "system", "content": system}] + formatted_messages
        payload = {
            "model": selected_model,
            "messages": formatted_messages,
            "temperature": temperature
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_bytes = resp.read()
                resp_json = json.loads(resp_bytes.decode("utf-8"))
                choice = resp_json["choices"][0]
                return choice["message"]
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            status = e.code
            if status in (401, 403):
                code = "AUTH"
            elif status == 429:
                code = "RATE_LIMIT"
            elif status in (400, 413):
                if "context" in err_msg.lower() or "maximum context" in err_msg.lower():
                    code = "CONTEXT_WINDOW_EXCEEDED"
                else:
                    code = "INVALID_REQUEST"
            elif status >= 500:
                code = "SERVER"
            else:
                code = f"HTTP_{status}"
            raise LlmError(f"LLM API HTTP Error ({status}): {err_msg}", code, status=status)
        except urllib.error.URLError as e:
            raise LlmError(f"LLM API Network Error: {e.reason}", "TRANSPORT")
        except LlmError:
            raise
        except Exception as e:
            raise LlmError(f"LLM API Request Error: {e}", "UNKNOWN")

    def chat_completion_stream(
        self, messages, tools=None, model=None, temperature=None,
        provider=None, system=None, **kwargs,
    ):
        request = dict(kwargs.get("request", kwargs))
        request.update(messages=messages, model=model, provider=provider)
        for key, value in (("tools", tools), ("system", system), ("temperature", temperature)):
            if value is not None:
                request[key] = value
        if provider and provider in self._adapters:
            adapter = self._adapters[provider]["adapter"]
            fn = getattr(adapter, "chat_completion_stream", None) or getattr(adapter, "stream", None)
            if callable(fn):
                import inspect
                parameters = inspect.signature(fn).parameters
                if "request" in parameters and "messages" not in parameters:
                    return fn(request=request)
                if "options" in parameters and "messages" not in parameters:
                    return fn(options=request)
                if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
                    return fn(**request)
                selected = {key: value for key, value in request.items() if key in parameters}
                if "request" in parameters:
                    selected["request"] = request
                if not selected and len(parameters) == 1:
                    return fn(request)
                return fn(**selected)
        return self._default_chat_completion_stream(
            messages=messages, tools=tools, model=model, temperature=temperature,
            provider=provider, system=system, options=request)

    def _default_chat_completion_stream(
        self, messages, tools=None, model=None, temperature=None,
        provider=None, system=None, options=None,
    ):
        from dsh.llm.deepseek_wire import serialize_request, parse_sse, translate
        from dsh.llm.http_stream import open_stream
        from dsh.llm.attribution import attribution_headers
        api_key = self.resolve_api_key(provider)
        base_url = self.resolve_base_url(provider)
        request = dict(options or {})
        request.update(messages=messages, tools=tools, system=system,
                       model=self.resolve_model(model, provider))
        if temperature is not None:
            request["temperature"] = temperature
        payload = request.get("_wire_payload")
        if payload is None:
            payload = serialize_request(request)
        req = urllib.request.Request(
            "{}/chat/completions".format(base_url.rstrip("/")),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={**attribution_headers(), **request.get("_provider_headers", {}), "Content-Type": "application/json", "Authorization": "Bearer {}".format(api_key),
                     "Accept": "text/event-stream"}, method="POST")
        try:
            with open_stream(req, request.get("signal"), request.get("streamIdleTimeoutMs", 300000), request.get("_on_activity")) as (response, chunks):
                if request.get("_on_accepted") is not None:
                    request["_on_accepted"]()
                yield from translate(parse_sse(chunks))
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                body = (error._dsh_body if hasattr(error, "_dsh_body") else error.read()).decode("utf-8", errors="replace")
            finally:
                error.close()
            from dsh.llm.provider_errors import http_error_code
            try:
                parsed = json.loads(body)
                detail = parsed.get("error") if isinstance(parsed, dict) else None
            except ValueError:
                detail = None
            code = http_error_code(status, detail)
            from email.utils import parsedate_to_datetime
            import time
            raw_delay = error.headers.get("retry-after", "")
            try:
                delay = float(raw_delay) * 1000 if raw_delay.isdigit() else (parsedate_to_datetime(raw_delay).timestamp() - time.time()) * 1000
                if not math.isfinite(delay) or delay <= 0:
                    delay = None
            except (ValueError, TypeError, OverflowError):
                delay = None
            request_id = error.headers.get("x-request-id") or error.headers.get("x-deepseek-request-id")
            message = detail.get("message") if isinstance(detail, dict) else None
            failure = LlmError(message if isinstance(message, str) and message else "DeepSeek API error (HTTP {})".format(status),
                               code, status=status, providerRetryAfterMs=delay, requestId=request_id or None)
            failure.provider_detail = " ".join(detail[key] for key in ("code", "type", "message") if isinstance(detail.get(key), str)) if isinstance(detail, dict) else ""
            raise failure from error
        except (urllib.error.URLError, OSError) as error:
            raise LlmError("LLM API Network Error: {}".format(error), "TRANSPORT") from error

    @Remote
    def listProviders(self):
        return [dict(value["provider"]) for value in self._adapters.values()]

    @Remote
    def listConfigurableProviders(self):
        return [dict(value, settingsPath=list(value["settingsPath"])) for value in self._directory.values()]

    @Remote("discoverModels")
    async def remoteDiscoverModels(self, settingsNs, request, signal):
        try:
            return await self.discover_models(settingsNs, request, signal)
        except Exception as error:
            details = {"settingsNs": settingsNs}
            if "baseURL" in request:
                details["baseURL"] = request["baseURL"]
            raise TypertRemoteFailure({"code": "model-discovery-failed", "message": str(error), "details": details}) from error

    # alias for 1:1 naming used by apiproxy handler
    def list_providers(self):
        # if adapters registered, return them; else static fallback for backward compat
        if self._adapters:
            return [dict(v["provider"]) for v in self._adapters.values()]
        return [
            {"id": "deepseek-official", "name": "DeepSeek"},
            {"id": "deepseek", "name": "DeepSeek Official"},
            {"id": "openai", "name": "OpenAI Compatible"}
        ]

    def list_configurable_providers(self):
        if self._directory:
            return [dict(provider=v["provider"], displayName=v["displayName"], settingsNs=v["settingsNs"], settingsPath=list(v["settingsPath"]), **({"declared": v["declared"]} if "declared" in v and v["declared"] is not None else {})) for v in self._directory.values()]
        return [
            {"provider": "deepseek-official", "displayName": "DeepSeek", "settingsNs": "llm-deepseek", "settingsPath": []},
            {"provider": "openai", "displayName": "OpenAI Compatible", "settingsNs": "llm-openai", "settingsPath": []},
            {"provider": "deepseek", "displayName": "DeepSeek Official", "settingsNs": "llm", "settingsPath": []}
        ]


class LlmRuntime:
    """
    Cordis plugin mounting LLMService on ctx.llm.
    1:1 aligned with reference packages/llm/llm.
    """
    id = "llm"
    name = "@deepseek-ai/dsh-llm"

    def __init__(self, config=None):
        self.config = config or {}

    def apply(self, ctx: Any) -> None:
        if not ctx.has("llm"):
            svc = LLMService(ctx=ctx)
            ctx.set_service("llm", svc)

