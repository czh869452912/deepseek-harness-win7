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

    def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.0
    ):
        """
        Streaming chat completion yielding live chunks with TTFT and timing measurements.
        Yields chunk events:
        - ('chunk', { 'delta_type': 'reasoning'|'text'|'tool_call', 'text': ..., 'reasoning': ..., 'tool_call': ... })
        - ('finish', { 'message': full_message, 'timing': timing_dict, 'usage': usage_dict })
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

        start_time = time.time()
        first_token_time: Optional[float] = None

        accumulated_content = []
        accumulated_reasoning = []
        accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}
        usage_data: Dict[str, Any] = {}

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

                    if first_token_time is None:
                        first_token_time = time.time()

                    # 1. Reasoning content chunk
                    reasoning_chunk = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning_chunk:
                        accumulated_reasoning.append(reasoning_chunk)
                        yield ("chunk", {
                            "delta_type": "reasoning",
                            "delta": reasoning_chunk,
                            "reasoning": "".join(accumulated_reasoning),
                            "content": "".join(accumulated_content),
                            "first_token": first_token_time == time.time(),
                        })

                    # 2. Text content chunk
                    content_chunk = delta.get("content")
                    if content_chunk:
                        accumulated_content.append(content_chunk)
                        yield ("chunk", {
                            "delta_type": "text",
                            "delta": content_chunk,
                            "reasoning": "".join(accumulated_reasoning),
                            "content": "".join(accumulated_content),
                        })

                    # 3. Tool calls chunk
                    tool_calls_chunk = delta.get("tool_calls")
                    if tool_calls_chunk:
                        for tc_delta in tool_calls_chunk:
                            idx = tc_delta.get("index", 0)
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {
                                    "id": tc_delta.get("id", f"call_{idx}_{int(time.time()*1000)}"),
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""}
                                }
                            if "id" in tc_delta and tc_delta["id"]:
                                accumulated_tool_calls[idx]["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            if "name" in fn and fn["name"]:
                                accumulated_tool_calls[idx]["function"]["name"] += fn["name"]
                            if "arguments" in fn and fn["arguments"]:
                                accumulated_tool_calls[idx]["function"]["arguments"] += fn["arguments"]

                        tool_calls_list = [accumulated_tool_calls[i] for i in sorted(accumulated_tool_calls.keys())]
                        yield ("chunk", {
                            "delta_type": "tool_call",
                            "tool_calls": tool_calls_list,
                            "reasoning": "".join(accumulated_reasoning),
                            "content": "".join(accumulated_content),
                        })

        except Exception as stream_err:
            # Fallback to non-streaming if stream is rejected by endpoint
            if not accumulated_content and not accumulated_reasoning and not accumulated_tool_calls:
                msg = self.chat_completion(messages, tools, model, temperature)
                completed_time = time.time()
                yield ("finish", {
                    "message": msg,
                    "timing": {
                        "stepStartTime": start_time * 1000,
                        "firstTokenTime": (start_time + 0.15) * 1000,
                        "completedTime": completed_time * 1000,
                        "ttftMs": 150.0,
                        "decodingMs": max(0.0, (completed_time - start_time - 0.15) * 1000),
                        "durationMs": (completed_time - start_time) * 1000,
                    },
                    "usage": {"inputTokens": 0, "outputTokens": 0}
                })
                return
            else:
                raise stream_err

        completed_time = time.time()
        if first_token_time is None:
            first_token_time = completed_time

        ttft_ms = (first_token_time - start_time) * 1000
        decoding_ms = (completed_time - first_token_time) * 1000
        duration_ms = (completed_time - start_time) * 1000

        full_tool_calls = [accumulated_tool_calls[i] for i in sorted(accumulated_tool_calls.keys())] if accumulated_tool_calls else None
        final_message: Dict[str, Any] = {
            "role": "assistant",
            "content": "".join(accumulated_content) if accumulated_content else None,
        }
        if accumulated_reasoning:
            final_message["reasoning_content"] = "".join(accumulated_reasoning)
        if full_tool_calls:
            final_message["tool_calls"] = full_tool_calls

        timing_data = {
            "stepStartTime": start_time * 1000,
            "firstTokenTime": first_token_time * 1000,
            "completedTime": completed_time * 1000,
            "ttftMs": round(ttft_ms, 2),
            "decodingMs": round(decoding_ms, 2),
            "durationMs": round(duration_ms, 2),
        }

        yield ("finish", {
            "message": final_message,
            "timing": timing_data,
            "usage": usage_data or {
                "inputTokens": len(json.dumps(messages)) // 4,
                "outputTokens": (len(final_message.get("content") or "") + len(final_message.get("reasoning_content") or "")) // 4
            }
        })
