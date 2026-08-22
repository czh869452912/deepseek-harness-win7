import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from dsh.cordis.environment import LaunchEnvironmentSnapshot


class LlmError(RuntimeError):
    def __init__(self, message, code, status=None, providerRetryAfterMs=None, requestId=None):
        if not isinstance(message, str) or not message:
            raise ValueError("LlmError message must be a non-empty string")
        if not isinstance(code, str) or not code:
            raise ValueError("LlmError code must be a non-empty string")
        super(LlmError, self).__init__(message)
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

    # ---- config resolution (unchanged) ----
    def resolve_api_key(self):
        if self.static_api_key:
            return self.static_api_key
        env_key = (
            os.environ.get(self.api_key_env)
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        if env_key:
            return env_key
        if self.ctx and self.ctx.has("credentials"):
            creds = self.ctx.get("credentials")
            try:
                val = creds.resolve(self.api_key_env) or creds.resolve("OPENAI_API_KEY")
            except Exception:
                val = None
            if val:
                # credentials.resolve may return dict {value:...} or str
                if isinstance(val, dict):
                    v = val.get("value")
                    if v:
                        return v
                elif isinstance(val, str) and val.strip():
                    return val
        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "api_key")
            if val:
                return val
            # also check llm-deepseek ns
            val2 = settings.get_setting("llm-deepseek", "apiKey")
            if val2:
                return val2
        if self.ctx and self.ctx.has("launch_environment"):
            launch_env = self.ctx.get("launch_environment")
            entry = (
                launch_env.get_from(self.api_key_env, ["project-env", "user-env"])
                or launch_env.get_from("DEEPSEEK_API_KEY", ["project-env", "user-env"])
                or launch_env.get_from("OPENAI_API_KEY", ["project-env", "user-env"])
            )
            if entry and entry.value:
                return entry.value
        raise LlmError(
            "LLM API Key missing for '{}'. Please provide --api-key, export DEEPSEEK_API_KEY environment variable, or configure ~/.dsh/.credentials.yaml.".format(self.api_key_env),
            "MISSING_CREDENTIAL"
        )

    def resolve_base_url(self):
        if self.static_base_url:
            return self.static_base_url.rstrip("/")
        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "base_url")
            if val:
                return str(val).rstrip("/")
            val2 = settings.get_setting("llm-deepseek", "baseURL")
            if val2:
                return str(val2).rstrip("/")
            val2 = settings.get_setting("llm-deepseek", "base_url")
            if val2:
                return str(val2).rstrip("/")
        env_url = (
            os.environ.get("DEEPSEEK_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        )
        if env_url:
            return env_url.rstrip("/")
        if self.ctx and self.ctx.has("launch_environment"):
            launch_env = self.ctx.get("launch_environment")
            entry = (
                launch_env.get_from("DEEPSEEK_BASE_URL", ["project-env", "user-env"])
                or launch_env.get_from("OPENAI_BASE_URL", ["project-env", "user-env"])
            )
            if entry and entry.value:
                return entry.value.rstrip("/")
        return "https://api.deepseek.com"

    def resolve_search_base_url(self):
        if self.static_search_base_url:
            return self.static_search_base_url.rstrip("/")
        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "search_base_url")
            if val:
                return str(val).rstrip("/")
        env_url = os.environ.get("DEEPSEEK_SEARCH_BASE_URL")
        if env_url:
            return env_url.rstrip("/")
        if self.ctx and self.ctx.has("launch_environment"):
            launch_env = self.ctx.get("launch_environment")
            entry = launch_env.get_from("DEEPSEEK_SEARCH_BASE_URL", ["project-env", "user-env"])
            if entry and entry.value:
                return entry.value.rstrip("/")
        return self.resolve_base_url()

    def resolve_model(self, req_model=None):
        if req_model:
            return req_model
        if self.static_model:
            return self.static_model
        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "model")
            if val:
                return str(val)
            val2 = settings.get_setting("llm-deepseek", "model")
            if val2:
                return str(val2)
        env_model = (
            os.environ.get("DEEPSEEK_MODEL")
            or os.environ.get("OPENAI_MODEL")
        )
        if env_model:
            return env_model
        if self.ctx and self.ctx.has("launch_environment"):
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
                info = adapter.provider_info(p) if hasattr(adapter, "provider_info") else {"id": p, "name": p}
            except Exception:
                info = {"id": p, "name": p}
            if not isinstance(info, dict) or info.get("id") != p or not info.get("name"):
                raise LlmError('adapter metadata for provider "{}" must preserve its id and have a non-empty name'.format(p), "INVALID_ADAPTER")
            unique.add(p)
            retry = None
            try:
                retry = adapter.provider_retry_policy(p) if hasattr(adapter, "provider_retry_policy") else None
            except Exception:
                retry = None
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
                info = adapter.provider_info(p) if hasattr(adapter, "provider_info") else {"id": p, "name": p}
                if not isinstance(info, dict) or info.get("id") != p or not info.get("name"):
                    raise LlmError('adapter metadata for provider "{}" must preserve its id and have a non-empty name'.format(p), "INVALID_ADAPTER")
                uniq2.add(p)
                retry = adapter.provider_retry_policy(p) if hasattr(adapter, "provider_retry_policy") else None
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

    async def discover_models(self, settings_ns, options):
        discover = self._discoveries.get(settings_ns)
        if discover is None:
            raise LlmError('no model discovery is registered for "{}"'.format(settings_ns), "NO_DISCOVERY")
        provider = options.get("provider") if isinstance(options, dict) else None
        base_url = options.get("baseURL") or options.get("base_url") if isinstance(options, dict) else None
        if not (provider and str(provider).strip()) and not (base_url and str(base_url).strip()):
            raise LlmError("model discovery needs a provider route or a baseURL", "INVALID_DISCOVERY")
        # call discovery
        import inspect as _ins
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
        if entry and hasattr(entry["adapter"], "list_models"):
            try:
                import inspect as _ins
                res = entry["adapter"].list_models(provider_id)
                if _ins.isawaitable(res):
                    res = await res
                # validate per spec
                seen = set()
                out = []
                for m in (res or []):
                    if not isinstance(m, dict) or m.get("provider") != provider_id or not m.get("id") or not m.get("name") or m["id"] in seen:
                        raise LlmError('adapter returned invalid or duplicate model metadata for provider "{}"'.format(provider_id), "INVALID_CATALOG")
                    seen.add(m["id"])
                    out.append({"id": m["id"], "name": m["name"], **({"description": m["description"]} if m.get("description") else {}), **({"reasoning": m["reasoning"]} if m.get("reasoning") else {})})
                return out
            except LlmError:
                raise
            except Exception as e:
                raise LlmError(str(e), "INVALID_CATALOG")
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

    def resolve_model_info(self, provider_id, model_id):
        # try adapter
        entry = self._adapters.get(provider_id)
        if entry and hasattr(entry["adapter"], "resolve_model"):
            import asyncio as _aio
            try:
                res = entry["adapter"].resolve_model(provider_id, model_id)
                if hasattr(res, "__await__"):
                    # run if loop exists else create
                    try:
                        loop = _aio.get_running_loop()
                        # can't block; fallback to sync version
                        return {"provider": provider_id, "id": model_id, "name": model_id}
                    except RuntimeError:
                        res = _aio.run(res)
                return res
            except Exception:
                pass
        return {"provider": provider_id, "id": model_id, "name": model_id}

    # backward compat alias
    def list_configurable_providers_sync(self):
        return self.list_configurable_providers()

    def chat_completion(
        self,
        messages,
        tools=None,
        model=None,
        temperature=0.0
    ):
        api_key = self.resolve_api_key()
        base_url = self.resolve_base_url()
        selected_model = self.resolve_model(model)
        url = "{}/chat/completions".format(base_url)
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(api_key)
        }
        payload = {
            "model": selected_model,
            "messages": messages,
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
            raise RuntimeError("LLM API HTTP Error ({}): {}".format(e.code, err_msg))
        except urllib.error.URLError as e:
            raise RuntimeError("LLM API Network Error: {}".format(e.reason))
        except Exception as e:
            raise RuntimeError("LLM API Request Error: {}".format(e))

    def chat_completion_stream(
        self,
        messages,
        tools=None,
        model=None,
        temperature=0.0
    ):
        import time
        api_key = self.resolve_api_key()
        base_url = self.resolve_base_url()
        selected_model = self.resolve_model(model)
        url = "{}/chat/completions".format(base_url)
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(api_key),
            "Accept": "text/event-stream"
        }
        payload = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True}
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        accumulated_content = []
        accumulated_reasoning = []
        accumulated_tool_calls = {}
        usage_data = {}
        text_block_started = False
        reasoning_block_started = False
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_json = json.loads(data_str)
                    except Exception:
                        continue
                    if "usage" in chunk_json and chunk_json["usage"]:
                        usage_data = chunk_json["usage"]
                    choices = chunk_json.get("choices")
                    if not choices or len(choices) == 0:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {})
                    reasoning_chunk = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning_chunk:
                        if not reasoning_block_started:
                            reasoning_block_started = True
                            yield {"type": "block-start", "index": 1, "blockType": "reasoning"}
                        accumulated_reasoning.append(reasoning_chunk)
                        yield {"type": "reasoning-delta", "index": 1, "text": reasoning_chunk}
                    content_chunk = delta.get("content")
                    if content_chunk:
                        if not text_block_started:
                            text_block_started = True
                            yield {"type": "block-start", "index": 0, "blockType": "text"}
                        accumulated_content.append(content_chunk)
                        yield {"type": "text-delta", "index": 0, "text": content_chunk}
                    tool_calls_chunk = delta.get("tool_calls")
                    if tool_calls_chunk:
                        for tc_delta in tool_calls_chunk:
                            idx = tc_delta.get("index", 0)
                            block_idx = 10 + idx
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {
                                    "id": tc_delta.get("id", "call_{}_{}".format(idx, int(time.time()*1000))),
                                    "name": "",
                                    "arguments": "",
                                    "started": False,
                                }
                            if "id" in tc_delta and tc_delta["id"]:
                                accumulated_tool_calls[idx]["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {}) if "function" in tc_delta else tc_delta
                            name_part = fn.get("name", "")
                            args_part = fn.get("arguments", "")
                            if name_part:
                                accumulated_tool_calls[idx]["name"] += name_part
                            if args_part:
                                accumulated_tool_calls[idx]["arguments"] += args_part
                            if not accumulated_tool_calls[idx]["started"]:
                                accumulated_tool_calls[idx]["started"] = True
                                yield {"type": "block-start", "index": block_idx, "blockType": "tool-call"}
                            yield {
                                "type": "tool-call-delta",
                                "index": block_idx,
                                "id": accumulated_tool_calls[idx]["id"],
                                "name": accumulated_tool_calls[idx]["name"],
                                "argumentsDelta": args_part,
                            }
        except Exception as stream_err:
            if not accumulated_content and not accumulated_reasoning and not accumulated_tool_calls:
                msg = self.chat_completion(messages, tools, model, temperature)
                content = msg.get("content", "")
                if content:
                    yield {"type": "block-start", "index": 0, "blockType": "text"}
                    yield {"type": "text-delta", "index": 0, "text": content}
                    yield {"type": "block-end", "index": 0, "block": {"type": "text", "text": content}}
                tcalls = msg.get("tool_calls", [])
                if tcalls:
                    for idx, tc in enumerate(tcalls):
                        func = tc.get("function", {}) if "function" in tc else tc
                        cid = tc.get("id", "call_{}".format(idx))
                        cname = func.get("name", "")
                        cargs = func.get("arguments", "")
                        yield {"type": "block-start", "index": 10 + idx, "blockType": "tool-call"}
                        yield {"type": "tool-call-delta", "index": 10 + idx, "id": cid, "name": cname, "argumentsDelta": cargs}
                        yield {"type": "block-end", "index": 10 + idx, "block": {"type": "tool-call", "id": cid, "name": cname, "arguments": cargs}}
                yield {"type": "usage", "usage": {"inputTokens": 0, "outputTokens": 0}}
                yield {"type": "finish", "reason": {"kind": "tool-calls" if tcalls else "stop"}}
                return
            else:
                raise stream_err
        if reasoning_block_started:
            yield {"type": "block-end", "index": 1, "block": {"type": "reasoning", "text": "".join(accumulated_reasoning)}}
        if text_block_started:
            yield {"type": "block-end", "index": 0, "block": {"type": "text", "text": "".join(accumulated_content)}}
        for idx, tc in sorted(accumulated_tool_calls.items()):
            block_idx = 10 + idx
            yield {"type": "block-end", "index": block_idx, "block": {
                "type": "tool-call",
                "id": tc["id"],
                "name": tc["name"],
                "arguments": tc["arguments"],
            }}
        final_usage = usage_data or {
            "inputTokens": len(json.dumps(messages)) // 4,
            "outputTokens": (len("".join(accumulated_content)) + len("".join(accumulated_reasoning))) // 4
        }
        yield {"type": "usage", "usage": final_usage}
        has_tools = bool(accumulated_tool_calls)
        yield {"type": "finish", "reason": {"kind": "tool-calls" if has_tools else "stop"}}

    # alias for 1:1 naming used by apiproxy handler
    def list_providers(self):
        # if adapters registered, return them; else static fallback for backward compat
        if self._adapters:
            return [dict(v["provider"]) for v in self._adapters.values()]
        return [
            {"id": "deepseek", "name": "DeepSeek Official"},
            {"id": "deepseek-official", "name": "DeepSeek"},
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
