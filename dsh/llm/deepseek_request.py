"""Native request transaction: images, file recovery, and extension acceptance."""
import asyncio
import concurrent.futures
import functools
import re
import time

from dsh.core.abort import AbortController
from dsh.cordis.utils import js_to_string
from dsh.core.cancellation import aborted
from dsh.llm.deepseek_wire import serialize_request
from dsh.llm.image_content import images, offload, serialize_images
from dsh.llm.llm_service import LlmError
from dsh.llm.stream_bridge import OwnedStream, iter_chunks


class FileResolutionFailure(Exception):
    pass


async def request_stream(adapter, transport, request, options):
    from dsh.llm.deepseek_file_store import DeepSeekFileStore
    controller = AbortController()
    signal, caller = controller.signal, request.get("signal")
    state = {"waiting": True, "since": time.monotonic(), "timeout": False}
    async def monitor():
        while not signal.aborted:
            if aborted(caller):
                controller.abort("caller cancelled")
            elif state["waiting"] and time.monotonic() - state["since"] > options["streamIdleTimeoutMs"] / 1000:
                state["timeout"] = True
                controller.abort("stream idle timeout")
            await asyncio.sleep(0.01)
    monitor_task = asyncio.create_task(monitor())
    reader = None
    try:
        versions = {}
        has_images = any(any(images(message.get("content"))) for message in request["messages"])
        attachments = adapter.ctx.get("attachments") if has_images else None
        def access(ref):
            fs = adapter.ctx.get("fs")
            location = getattr(attachments, "imageHostPath", None)
            mapping = getattr(fs, "processPathFromHostPath", None)
            if location is None or mapping is None:
                return None
            host_path = location(ref)
            return mapping(host_path) if host_path is not None else None
        model = next((row for row in options["models"] if row["id"] == request["model"]), {})
        if has_images:
            if "image" not in model.get("inputModalities", []):
                raise LlmError("This DeepSeek model does not accept image input", "UNSUPPORTED_CONTENT")
            if attachments is None:
                raise LlmError("DeepSeek image conversion requires the durable attachment service", "UNSUPPORTED_CONTENT")
            request = dict(request, messages=offload(request["messages"], options["maxRequestFilesBytes"],
                options["maxImagesPerRequest"], options["imageOffloadByteQuantum"], options["imageOffloadCountQuantum"],
                lambda ref: min(ref["bytes"], model["imageMaxBytes"]), access=access))
            refs = {block["attachment"]["attachmentId"]: block["attachment"]
                    for message in request["messages"] for block in images(message.get("content"))}
            policy = {"maxPixels": model["imagePixelBudget"], "maxBytes": model["imageMaxBytes"]}
            for key, ref in refs.items():
                signal.throw_if_aborted()
                versions[key] = await asyncio.get_running_loop().run_in_executor(None,
                    functools.partial(attachments.read_image_request, ref, policy, signal))
                state["since"] = time.monotonic()
            if adapter.files is None:
                adapter.files = DeepSeekFileStore()
        connection = {"baseURL": options["baseURL"], "apiKey": transport.resolve_api_key(),
                      "filesApiTimeoutMs": options["filesApiTimeoutMs"]}
        file_policy = {"expiresAfterSeconds": options["fileExpiresAfterSeconds"],
                       "refreshMarginSeconds": options["fileRefreshMarginSeconds"],
                       "quotaCleanupBatch": options["fileQuotaCleanupBatch"]}
        inline, file_attempt = False, 0
        while True:
            signal.throw_if_aborted()
            used = []
            async def resolve(version, location):
                try:
                    result = await asyncio.wait_for(adapter.files.ensure_uploaded(version, connection, file_policy, signal),
                                                    options["filesApiTimeoutMs"] / 1000)
                except Exception as error:
                    if signal.aborted:
                        raise
                    raise FileResolutionFailure() from error
                state["since"] = time.monotonic()
                used.append({"version": version, "fileId": result["record"]["fileId"], "location": location})
                return result["record"]["fileId"]
            if has_images:
                messages = offload(request["messages"], options["maxInlineRequestImageBytes"] if inline else options["maxRequestFilesBytes"],
                    options["maxImagesPerRequest"], options["inlineImageOffloadByteQuantum"] if inline else options["imageOffloadByteQuantum"],
                    options["imageOffloadCountQuantum"], lambda ref: versions[ref["attachmentId"]]["bytes"], base64=inline, access=access)
                try:
                    body = await serialize_images(dict(request, messages=messages), versions, None if inline else resolve, access=access)
                except FileResolutionFailure:
                    inline = True
                    continue
            else:
                body = serialize_request(request, request.get('_request_defaults'))
            extensions = adapter.ctx.get("deepseekLlmApiExtensions")
            prepared = None
            if extensions is not None:
                try:
                    extension_request = {"body": body, "signal": signal}
                    extension_request.update({key: request[key] for key in ("sessionId", "purpose") if request.get(key) is not None})
                    prepared = await extensions.prepare(extension_request)
                    if any(field in body for field in prepared.fields):
                        raise ValueError("extension field collides with base request")
                    body = dict(body, **prepared.fields)
                except Exception as error:
                    raise LlmError("DeepSeek request extension preparation failed", "REQUEST_EXTENSION") from error
            loop = asyncio.get_running_loop()
            def accepted():
                if prepared is None:
                    return
                async def accept():
                    await prepared.accept()
                future = asyncio.run_coroutine_threadsafe(accept(), loop)
                try:
                    while True:
                        if signal.aborted:
                            raise LlmError("DeepSeek acceptance cancelled", "ABORTED")
                        try:
                            future.result(timeout=0.02)
                            return
                        except concurrent.futures.TimeoutError:
                            pass
                except Exception as error:
                    if not future.done():
                        future.cancel()
                    if isinstance(error, LlmError):
                        raise
                    raise LlmError("DeepSeek request extension acceptance failed", "REQUEST_EXTENSION") from error
            resolved = dict(request, _wire_payload=body, _on_accepted=accepted,
                            _on_activity=lambda: state.update(since=time.monotonic()))
            stream = OwnedStream(lambda owned: transport._default_chat_completion_stream(
                resolved["messages"], tools=resolved.get("tools"), model=resolved["model"],
                system=resolved.get("system"), options=dict(resolved, signal=owned)), signal,
                on_settled=lambda: state.update(waiting=False))
            reader = iter_chunks(stream)
            try:
                async for chunk in reader:
                    state["waiting"] = False
                    yield chunk
                    state.update(waiting=True, since=time.monotonic())
                return
            except LlmError as error:
                detail = getattr(error, "provider_detail", str(error))
                stale = used and error.status is not None and re.search(r"\bfile(?:[_ -]?(?:id|api))?", detail, re.I) and (
                    re.search(r"expired|not[_ -]?found|deleted|do(?:es)? not exist|not created under (?:this|your) account", detail, re.I)
                    or re.search(r"invalid.{0,20}file[_ -]?(?:id|api)|file[_ -]?(?:id|api).{0,20}invalid", detail, re.I))
                if stale:
                    unique = {(row["version"]["variantId"], row["fileId"]): row for row in used}
                    exact = [row for row in unique.values() if re.search(r"(?<![\w-])" + re.escape(row["fileId"]) + r"(?![\w-])", detail)]
                    for row in exact or list(unique.values()):
                        await adapter.files.invalidate(row["version"], row["fileId"], connection)
                    if file_attempt == 0:
                        file_attempt += 1
                        continue
                if used and error.status == 400 and re.search(
                        r"(?:unsupported|invalid|cannot read|failed to (?:decode|process)).{0,40}image|image.{0,40}(?:unsupported|invalid|cannot be decoded)", detail, re.I):
                    def facts(row):
                        version, location = row["version"], row["location"]
                        ref = version["attachment"]
                        return '"{}" at message {}, image {} ({}, 8-bit {}, {}x{})'.format(
                            ref.get("name", ref["attachmentId"]), location["message"], location["image"],
                            version["mediaType"], "sRGBA" if version["hasAlpha"] else "sRGB", version["width"], version["height"])
                    exact = next((row for row in used if re.search(r"(?<![\w-])" + re.escape(row["fileId"]) + r"(?![\w-])", detail)), None)
                    target = exact or (used[0] if len(used) == 1 else None)
                    message = ("DeepSeek rejected normalized image {}: {}. ".format(facts(target), error.failure["message"]) if target else
                        "DeepSeek rejected a normalized request image: {}. Candidate images: {}. ".format(error.failure["message"], "; ".join(dict.fromkeys(facts(row) for row in used))))
                    message += "The provider rejected bytes already normalized by the harness; PNG, JPEG, WebP, and GIF remain supported input formats."
                    raise LlmError(message, error.code, status=error.status,
                        providerRetryAfterMs=error.providerRetryAfterMs, requestId=error.requestId) from error
                raise
            finally:
                await reader.aclose()
                reader = None
    except Exception as error:
        if state["timeout"]:
            raise LlmError("DeepSeek stream idle timeout after {}ms".format(js_to_string(options["streamIdleTimeoutMs"])), "TIMEOUT") from error
        if aborted(caller):
            raise LlmError("DeepSeek request aborted by caller", "ABORTED") from error
        raise
    finally:
        controller.abort("stream consumer stopped")
        monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)
        if reader is not None:
            await reader.aclose()
