import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


class LLMService:
    """
    LLM Service registered at `ctx.llm`.
    Supports OpenAI-compatible API endpoints (DeepSeek, OpenAI, etc.)
    with per-request dynamic resolution of api_key, base_url, and model.
    """

    def __init__(
        self,
        ctx: Optional[Any] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key_env: str = "DEEPSEEK_API_KEY"
    ):
        self.ctx = ctx
        self.static_api_key = api_key if (api_key and api_key.strip()) else None
        self.static_base_url = base_url if (base_url and base_url.strip()) else None
        self.static_model = model if (model and model.strip()) else None
        self.api_key_env = api_key_env

    def resolve_api_key(self) -> str:
        if self.static_api_key:
            return self.static_api_key

        if self.ctx and self.ctx.has("credentials"):
            creds = self.ctx.get("credentials")
            val = creds.resolve(self.api_key_env) or creds.resolve("OPENAI_API_KEY")
            if val:
                return val

        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "api_key")
            if val:
                return val

        env_key = (
            os.environ.get(self.api_key_env)
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        if env_key:
            return env_key

        raise RuntimeError(
            f"LLM API Key missing for '{self.api_key_env}'. "
            "Please provide --api-key, set DEEPSEEK_API_KEY environment variable, or configure ~/.dsh/credentials.json."
        )

    def resolve_base_url(self) -> str:
        if self.static_base_url:
            return self.static_base_url.rstrip("/")

        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "base_url")
            if val:
                return val.rstrip("/")

        env_url = (
            os.environ.get("DEEPSEEK_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        )
        if env_url:
            return env_url.rstrip("/")

        return "https://api.deepseek.com"

    def resolve_model(self, req_model: Optional[str] = None) -> str:
        if req_model:
            return req_model

        if self.static_model:
            return self.static_model

        if self.ctx and self.ctx.has("settings"):
            settings = self.ctx.get("settings")
            val = settings.get_setting("llm", "model")
            if val:
                return val

        env_model = (
            os.environ.get("DEEPSEEK_MODEL")
            or os.environ.get("OPENAI_MODEL")
        )
        if env_model:
            return env_model

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
