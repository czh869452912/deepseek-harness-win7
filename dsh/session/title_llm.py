"""First-prompt title generation using a bounded auxiliary native LLM call."""
import asyncio
import json

from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.llm.llm_service import LlmError
from dsh.llm.message import create_user_message
from dsh.session.title import normalize_session_title


class FirstPromptTitlePlugin(Plugin):
    id = "session-title-first-prompt-llm"
    inject = ["sessionTitle", "llm", "sessions"]

    def apply(self, ctx):
        config = dict(self.config)
        required = ("targetWords", "targetCjkCharacters", "maxInputBytes", "maxOutputTokens", "timeoutMs")
        if set(config) - set(required) - {"provider", "model"}:
            raise ValueError("session-title-llm: unknown configuration key")
        for key in required:
            if type(config.get(key)) is not int or config[key] < 1:
                raise ValueError("session-title-llm: " + key + " must be a positive integer")
        if config["timeoutMs"] > 2147483647:
            raise ValueError("session-title-llm timeout exceeds timer range")
        if ("provider" in config) != ("model" in config) or any(not isinstance(config[key], str) or not config[key] for key in ("provider", "model") if key in config):
            raise ValueError("session-title-llm: provider and model must be paired non-empty strings")
        async def generate(request):
            request["signal"].throw_if_aborted()
            selected = request["messages"][:1]
            if not selected:
                raise ValueError("first-prompt title provider requires one human message")
            framed = "Generate the session title from this JSON array of human messages:\n" + json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
            if len(framed.encode("utf-8")) > config["maxInputBytes"]:
                raise ValueError("session-title-llm: framed input exceeds maxInputBytes")
            route = {key: config[key] for key in ("provider", "model")} if "provider" in config else request.get("route")
            if route is None:
                raise ValueError("session-title-llm: no logged request route; configure provider and model together")
            system = "\n".join([
                "Create a concise title for an AI coding-assistant session from the supplied human messages.",
                "Return only the title on one line, **in plain text of natural language**, with no quotes, prefix, explanation, Markdown, XML, or terminal control codes. No code is allowed.",
                "Use the language of the messages.",
                "Aim for about {} words in non-CJK languages or {} CJK characters.".format(config["targetWords"], config["targetCjkCharacters"]),
            ])
            messages = [create_user_message({"content": [{"type": "text", "text": framed}], "source": {"kind": "plugin", "plugin": "dsh-session-title-llm"}})]
            controller, timed_out = AbortController(), [False]
            undo = request["signal"].add_listener("abort", lambda *_: controller.abort("title cancelled"))
            def timeout():
                timed_out[0] = True
                controller.abort("SESSION_TITLE_TIMEOUT")
            timer = asyncio.get_running_loop().call_later(config["timeoutMs"] / 1000, timeout)
            stream = ctx.get("llm").stream(dict(route, messages=messages, system=system, maxTokens=config["maxOutputTokens"],
                sessionId=request["session"].id, purpose="session-title", signal=controller.signal))
            try:
                request["session"].append("session/title-llm-request", {"titleProvider": self.id,
                    "messageSeqs": [row["seq"] for row in selected], "route": route, "system": system,
                    "messages": messages, "maxTokens": config["maxOutputTokens"]})
                from dsh.core.agent_loop import BlockAssembler
                assembler = BlockAssembler()
                async def consume():
                    async for chunk in stream:
                        controller.signal.throw_if_aborted()
                        assembler.push(chunk)
                task = asyncio.create_task(consume())
                aborted = asyncio.create_task(controller.signal.wait_aborted())
                try:
                    await asyncio.wait((task, aborted), return_when=asyncio.FIRST_COMPLETED)
                    if controller.signal.aborted:
                        task.cancel()
                    await task
                    controller.signal.throw_if_aborted()
                finally:
                    aborted.cancel()
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, aborted, return_exceptions=True)
                finish = assembler.finish
                if finish["kind"] != "stop":
                    failure = finish.get("failure", {})
                    raise LlmError(failure.get("message", "Title generation stopped: " + finish["kind"]), failure.get("code", "TITLE_GENERATION_FAILED"))
                blocks = assembler.blocks()
                if any(block["type"] == "tool-call" for block in blocks):
                    raise ValueError("title output must contain text only")
                title = normalize_session_title(" ".join(block["text"] for block in blocks if block["type"] == "text"), 9007199254740991)
                if not title:
                    raise ValueError("title model produced no text")
                return {"title": title, "messageSeqs": [row["seq"] for row in selected], "model": route}
            except (Exception, asyncio.CancelledError) as error:
                if timed_out[0]:
                    raise LlmError("Session title request timed out", "SESSION_TITLE_TIMEOUT") from error
                raise
            finally:
                timer.cancel()
                undo()
                await stream.aclose()
        ctx.get("sessionTitle").register({"id": self.id, "automatic": "first-prompt", "generate": generate})
