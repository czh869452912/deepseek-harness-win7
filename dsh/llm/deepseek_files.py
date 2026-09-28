"""Validated DeepSeek Files API transport with owned request cancellation."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from dsh.llm.http_stream import open_stream
from dsh.llm.llm_service import LlmError
from dsh.llm.attribution import attribution_headers

MAX_FILE_UPLOAD_BYTES = 128 * 1024 * 1024


class DeepSeekFilesError(LlmError):
    def __init__(self, message, status, detail):
        code = "AUTH" if status in (401, 403) else "RATE_LIMIT" if status == 429 else "SERVER" if status >= 500 else "FILES_API"
        super().__init__(message, code, status=status)
        self.detail = detail


def is_files_quota_error(error):
    return isinstance(error, DeepSeekFilesError) and bool(re.search(
        r"quota|storage|stored files|file count|too many files", error.detail, re.I))


def invalid(operation):
    return LlmError("DeepSeek Files API returned an invalid " + operation + " response.", "INVALID_RESPONSE")


def safe_integer(value):
    return type(value) is int and 0 <= value <= 9007199254740991


def parse_file(value, operation):
    if (not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]
            or value.get("object") != "file" or not safe_integer(value.get("bytes"))
            or not safe_integer(value.get("created_at")) or not isinstance(value.get("filename"), str)
            or not value["filename"] or value.get("purpose") != "user_data"
            or "expires_at" in value and not safe_integer(value["expires_at"])):
        raise invalid(operation)
    result = {"id": value["id"], "bytes": value["bytes"], "createdAt": value["created_at"],
              "filename": value["filename"], "purpose": "user_data"}
    if "expires_at" in value:
        result["expiresAt"] = value["expires_at"]
    return result


class DeepSeekFilesClient:
    def __init__(self, base_url, api_key, timeout_ms=60000):
        self.base_url, self.api_key, self.timeout_ms = base_url.rstrip("/"), api_key, timeout_ms

    def _request(self, path, operation, method="GET", data=None, content_type=None, signal=None):
        headers = dict(attribution_headers(), Authorization="Bearer " + self.api_key)
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with open_stream(request, signal, self.timeout_ms) as (_, chunks):
                body = b"".join(chunks)
        except urllib.error.HTTPError as error:
            detail, message = "", None
            try:
                parsed = json.loads(error._dsh_body)
                fields = parsed.get("error") if isinstance(parsed, dict) else None
                if isinstance(fields, dict):
                    message = fields.get("message") if isinstance(fields.get("message"), str) else None
                    detail = " ".join(fields[k] for k in ("code", "type", "message") if isinstance(fields.get(k), str))
            except (ValueError, AttributeError):
                pass
            raise DeepSeekFilesError(message or "DeepSeek Files API error (HTTP {})".format(error.code), error.code, detail) from error
        except LlmError:
            raise
        except (OSError, ValueError) as error:
            raise LlmError("DeepSeek Files API request failed", "TRANSPORT") from error
        try:
            return json.loads(body)
        except (ValueError, UnicodeError) as error:
            raise invalid(operation) from error

    def upload(self, data, media_type, filename, expires_after_seconds, signal=None):
        if len(data) > MAX_FILE_UPLOAD_BYTES:
            raise LlmError("DeepSeek Files API upload exceeds 128 MiB.", "INVALID_REQUEST")
        if type(expires_after_seconds) is not int or not 3600 <= expires_after_seconds <= 2592000:
            raise LlmError("DeepSeek file expiry must be between 3600 and 2592000 seconds.", "INVALID_REQUEST")
        boundary = "dsh-" + uuid.uuid4().hex
        parts = []
        for name, value in (("purpose", "user_data"), ("expires_after[anchor]", "created_at"),
                            ("expires_after[seconds]", str(expires_after_seconds))):
            parts.append(("--{}\r\nContent-Disposition: form-data; name=\"{}\"\r\n\r\n{}\r\n".format(boundary, name, value)).encode("utf-8"))
        escaped = filename.replace("\r", "%0D").replace("\n", "%0A").replace('"', "%22")
        if media_type not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            raise LlmError("Unsupported image media type", "INVALID_REQUEST")
        parts.extend([("--{}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{}\"\r\nContent-Type: {}\r\n\r\n".format(
            boundary, escaped, media_type)).encode("utf-8"), bytes(data), ("\r\n--{}--\r\n".format(boundary)).encode("ascii")])
        result = parse_file(self._request("/files", "upload", "POST", b"".join(parts),
                                         "multipart/form-data; boundary=" + boundary, signal), "upload")
        if "expiresAt" not in result:
            raise invalid("upload")
        return result

    def list(self, after=None, limit=None, order=None, signal=None):
        query = {"purpose": "user_data"}
        query.update({k: v for k, v in (("after", after), ("limit", limit), ("order", order)) if v is not None})
        value = self._request("/files?" + urllib.parse.urlencode(query), "list", signal=signal)
        if (not isinstance(value, dict) or value.get("object") != "list" or not isinstance(value.get("data"), list)
                or type(value.get("has_more")) is not bool
                or any(k in value and not isinstance(value[k], str) for k in ("first_id", "last_id"))):
            raise invalid("list")
        result = {"data": [parse_file(row, "list") for row in value["data"]], "hasMore": value["has_more"]}
        for key, target in (("first_id", "firstId"), ("last_id", "lastId")):
            if key in value:
                result[target] = value[key]
        return result

    def retrieve(self, file_id, signal=None):
        return parse_file(self._request("/files/" + urllib.parse.quote(file_id, safe=""), "retrieve", signal=signal), "retrieve")

    def delete(self, file_id, signal=None):
        value = self._request("/files/" + urllib.parse.quote(file_id, safe=""), "delete", "DELETE", signal=signal)
        if not isinstance(value, dict) or value.get("id") != file_id or value.get("object") != "file" or value.get("deleted") is not True:
            raise invalid("delete")
