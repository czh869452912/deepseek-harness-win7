import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from dsh.cordis.environment import LaunchEnvironmentSnapshot


class LLMService:
    """
    LLM Service registered at `ctx.llm`.
    Supports OpenAI-compatible API endpoints (DeepSeek, OpenAI, etc.)
    with layered configuration resolution for api_key, base_url, search_base_url, and model.
    """

    def __init__(
        self,
        ctx: Optional[Any] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        search_base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key_env: str = "DEEPSEEK_API_KEY"
    ):
        self.ctx = ctx
        self.static_api_key = api_key if (api_key and api_key.strip()) else None
        self.static_base_url = base_url if (base_url and base_url.strip()) else None
        self.static_search_base_url = search_base_url if (search_base_url and search_base_url.strip()) else None
        self.static_model = model if (model and model.strip()) else None
        self.api_key_env = api_key_env

    def resolve_api_key(self) -> str:
        # 1. Explicit / static call argument
        if self.static_api_key:
            return self.static_api_key

        # 2. Inherited launch environment (highest precedence for secrets)
        env_key = (
            os.environ.get(self.api_key_env)
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        if env_key:
            return env_key

        # 3. Managed credentials service ($DSH_HOME/.credentials.yaml)
        if self.ctx and self.ctx.has("credentials"):
            creds = self.ctx.get("credentials")
            val = creds.resolve(self.api_key_env) or creds.resolve("OPENAI_API_KEY")
            if val:
                return val

        # 4. User settings file ($DSH_HOME/settings.yaml)
        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "api_key")
            if val:
                return val

        # 5. Discovered .env fallback layers
        if self.ctx and self.ctx.has("launch_environment"):
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = (
                launch_env.get_from(self.api_key_env, ["project-env", "user-env"])
                or launch_env.get_from("DEEPSEEK_API_KEY", ["project-env", "user-env"])
                or launch_env.get_from("OPENAI_API_KEY", ["project-env", "user-env"])
            )
            if entry and entry.value:
                return entry.value

        raise RuntimeError(
            f"LLM API Key missing for '{self.api_key_env}'. "
            "Please provide --api-key, export DEEPSEEK_API_KEY environment variable, or configure ~/.dsh/.credentials.yaml."
        )

    def resolve_base_url(self) -> str:
        # 1. Explicit / static CLI parameter
        if self.static_base_url:
            return self.static_base_url.rstrip("/")

        # 2. User settings file ($DSH_HOME/settings.yaml)
        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "base_url")
            if val:
                return str(val).rstrip("/")

        # 3. Inherited process environment
        env_url = (
            os.environ.get("DEEPSEEK_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        )
        if env_url:
            return env_url.rstrip("/")

        # 4. Discovered .env fallback layers
        if self.ctx and self.ctx.has("launch_environment"):
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = (
                launch_env.get_from("DEEPSEEK_BASE_URL", ["project-env", "user-env"])
                or launch_env.get_from("OPENAI_BASE_URL", ["project-env", "user-env"])
            )
            if entry and entry.value:
                return entry.value.rstrip("/")

        # 5. Public default
        return "https://api.deepseek.com"

    def resolve_search_base_url(self) -> str:
        """Dedicated search endpoint resolution (DEEPSEEK_SEARCH_BASE_URL)."""
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
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = launch_env.get_from("DEEPSEEK_SEARCH_BASE_URL", ["project-env", "user-env"])
            if entry and entry.value:
                return entry.value.rstrip("/")

        return self.resolve_base_url()

    def resolve_model(self, req_model: Optional[str] = None) -> str:
        # 1. Per-request or static model override
        if req_model:
            return req_model
        if self.static_model:
            return self.static_model

        # 2. User settings file ($DSH_HOME/settings.yaml)
        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "model")
            if val:
                return str(val)

        # 3. Inherited process environment
        env_model = (
            os.environ.get("DEEPSEEK_MODEL")
            or os.environ.get("OPENAI_MODEL")
        )
        if env_model:
            return env_model

        # 4. Discovered .env fallback layers
        if self.ctx and self.ctx.has("launch_environment"):
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = (
                launch_env.get_from("DEEPSEEK_MODEL", ["project-env", "user-env"])
                or launch_env.get_from("OPENAI_MODEL", ["project-env", "user-env"])
            )
            if entry and entry.value:
                return entry.value

        # 5. Public default
        return "deepseek-chat"

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.0
    ) -> Dict[str, Any]:
        api_key = self.resolve_api_key()
        base_url = self.resolve_base_url()
        selected_model = self.resolve_model(model)

        url = f"{base_url}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload: Dict[str, Any] = {
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
            raise RuntimeError(f"LLM API HTTP Error ({e.code}): {err_msg}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"LLM API Network Error: {e.reason}")
        except Exception as e:
            raise RuntimeError(f"LLM API Request Error: {e}")

    def list_providers(self) -> List[Dict[str, Any]]:
        return [
            {"id": "deepseek", "name": "DeepSeek Official"},
            {"id": "openai", "name": "OpenAI Compatible"}
        ]

    def list_configurable_providers(self) -> List[Dict[str, Any]]:
        return [
            {"provider": "deepseek", "displayName": "DeepSeek Official", "settingsNs": "llm", "settingsPath": []},
            {"provider": "openai", "displayName": "OpenAI Compatible", "settingsNs": "llm", "settingsPath": []}
        ]

    def list_models(self, provider_id: str = "deepseek") -> List[Dict[str, Any]]:
        return [
            {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)", "description": "High efficiency general reasoning"},
            {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)", "description": "Deep reasoning with explicit chain-of-thought"}
        ]

    def resolve_model_info(self, provider_id: str, model_id: str) -> Dict[str, Any]:
        return {
            "provider": provider_id,
            "id": model_id,
            "name": model_id,
        }

    async def discover_models(self, settings_ns: str, options: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)"},
            {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)"}
        ]

    def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.0
    ):
        """
        Streaming chat completion yielding canonical 1:1 StreamChunk objects.
        Yields StreamChunks:
        - { 'type': 'block-start', 'index': 0, 'blockType': 'text'|'reasoning'|'tool-call' }
        - { 'type': 'text-delta'|'reasoning-delta', 'index': ..., 'text': ... }
        - { 'type': 'tool-call-delta', 'index': ..., 'id': ..., 'name': ..., 'argumentsDelta': ... }
        - { 'type': 'block-end', 'index': ..., 'block': ... }
        - { 'type': 'usage', 'usage': ... }
        - { 'type': 'finish', 'reason': { 'kind': 'stop'|'tool-calls'|'max-tokens' } }
        """
        import time

        api_key = self.resolve_api_key()
        base_url = self.resolve_base_url()
        selected_model = self.resolve_model(model)

        url = f"{base_url}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "text/event-stream"
        }

        payload: Dict[str, Any] = {
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
        accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}
        usage_data: Dict[str, Any] = {}

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

                    # 1. Reasoning content chunk
                    reasoning_chunk = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning_chunk:
                        if not reasoning_block_started:
                            reasoning_block_started = True
                            yield {"type": "block-start", "index": 1, "blockType": "reasoning"}
                        accumulated_reasoning.append(reasoning_chunk)
                        yield {"type": "reasoning-delta", "index": 1, "text": reasoning_chunk}

                    # 2. Text content chunk
                    content_chunk = delta.get("content")
                    if content_chunk:
                        if not text_block_started:
                            text_block_started = True
                            yield {"type": "block-start", "index": 0, "blockType": "text"}
                        accumulated_content.append(content_chunk)
                        yield {"type": "text-delta", "index": 0, "text": content_chunk}

                    # 3. Tool calls chunk
                    tool_calls_chunk = delta.get("tool_calls")
                    if tool_calls_chunk:
                        for tc_delta in tool_calls_chunk:
                            idx = tc_delta.get("index", 0)
                            block_idx = 10 + idx
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {
                                    "id": tc_delta.get("id", f"call_{idx}_{int(time.time()*1000)}"),
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
                        cid = tc.get("id", f"call_{idx}")
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
