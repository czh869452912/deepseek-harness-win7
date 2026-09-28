"""Bounded Connection body reader and socket-owned request cancellation."""
import asyncio
import inspect

from dsh.core.abort import AbortController

DEFAULT_MAX_REQUEST_BODY_BYTES = 300 * 1024 * 1024


class BodyTooLarge(Exception):
    pass


async def read_body(request, limit):
    if not request.get("body_deferred"):
        body = request.get("body", b"")
        if len(body) > limit:
            raise BodyTooLarge()
        return body
    reader, headers = request["reader"], request["headers"]
    if headers.get("transfer-encoding", "").lower() == "chunked":
        chunks, length = [], 0
        while True:
            line = await reader.readline()
            size = int(line.split(b";", 1)[0].strip(), 16)
            if size < 0:
                raise ValueError("negative chunk size")
            if size == 0:
                while True:
                    trailer = await reader.readline()
                    if trailer in (b"\r\n", b"\n", b""):
                        return b"".join(chunks)
            length += size
            if length > limit:
                raise BodyTooLarge()
            chunks.append(await reader.readexactly(size))
            if await reader.readexactly(2) != b"\r\n":
                raise ValueError("invalid chunk terminator")
    length = int(headers.get("content-length", "0"))
    if length < 0:
        raise ValueError("negative body length")
    if length > limit:
        raise BodyTooLarge()
    return await reader.readexactly(length)


async def write_response(writer, response):
    writer.write_status(response["status"])
    for name, value in response.get("headers", {}).items():
        writer.write_header(name, str(value))
    body = response.get("body", b"")
    if isinstance(body, str):
        body = body.encode("utf-8")
    if isinstance(body, bytes):
        writer.write_header("Content-Length", str(len(body)))
        writer.write_body(body)
    else:
        async for chunk in body:
            await writer.write_chunk(chunk)
    await writer.finish()


def bridge_handler(connection, fetch, limit=DEFAULT_MAX_REQUEST_BODY_BYTES):
    async def handler(request, response):
        rejection = connection.request_rejection(request)
        if rejection is not None:
            await write_response(response, {"status": rejection, "body": "unauthorized" if rejection == 401 else "forbidden"})
            return
        try:
            body = await read_body(request, limit)
        except BodyTooLarge:
            await write_response(response, {"status": 413, "body": "request body too large"})
            return
        except (ValueError, asyncio.IncompleteReadError):
            await write_response(response, {"status": 400, "body": "invalid request body"})
            return
        controller = AbortController()
        async def disconnected():
            reader = request.get("reader")
            if reader is not None:
                try:
                    while await reader.read(1024):
                        pass
                except (ConnectionError, OSError):
                    pass
                finally:
                    controller.abort("HTTP client disconnected")
        monitor = asyncio.create_task(disconnected())
        try:
            result = fetch(dict(request, body=body, signal=controller.signal))
            if inspect.isawaitable(result):
                result = await result
            await write_response(response, result)
        finally:
            controller.abort("HTTP response ended")
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
    handler.defer_body = True
    return handler
