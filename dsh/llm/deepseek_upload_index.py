"""Atomic, credential-namespaced durable DeepSeek image upload mappings."""
import copy
import hashlib
import json
import os
import re
import uuid

from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.file_lock import with_file_lock
from dsh.llm.deepseek_files import safe_integer


def file_scope(base_url, api_key):
    return hashlib.sha256((base_url.rstrip("/") + "\0" + api_key).encode("utf-8")).hexdigest()


def parse_record(value):
    if (not isinstance(value, dict)
            or not isinstance(value.get("scope"), str) or not re.fullmatch(r"[a-f0-9]{64}", value["scope"])
            or any(not isinstance(value.get(k), str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", value[k]) for k in ("attachmentId", "variantId"))
            or not isinstance(value.get("fileId"), str) or not value["fileId"]
            or any(not safe_integer(value.get(k)) for k in ("bytes", "createdAt", "expiresAt"))):
        raise ValueError("invalid upload mapping")
    return {k: value[k] for k in ("scope", "attachmentId", "variantId", "fileId", "bytes", "createdAt", "expiresAt")}


def reusable(record, now, margin):
    return record["expiresAt"] - now > margin


class DeepSeekUploadIndex:
    def __init__(self, path=None):
        self.path = os.path.abspath(path or os.path.join(resolve_dsh_home(), "llm-deepseek", "files-v3.json"))

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as stream:
                value = json.load(stream)
            if not isinstance(value, dict) or value.get("formatVersion") != 3 or not isinstance(value.get("records"), list):
                raise ValueError("unsupported upload index")
            records = [parse_record(row) for row in value["records"]]
            keys = {(row["scope"], row["variantId"]) for row in records}
            if len(keys) != len(records):
                raise ValueError("duplicate upload mapping")
            return records
        except (FileNotFoundError, ValueError, UnicodeError):
            return []

    def _save(self, records):
        parent = os.path.dirname(self.path)
        os.makedirs(parent, mode=0o700, exist_ok=True)
        temporary = self.path + "." + uuid.uuid4().hex + ".tmp"
        try:
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"formatVersion": 3, "records": records}, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    async def get(self, scope, variant_id, now, refresh_margin_ms):
        return next((row for row in self._load() if row["scope"] == scope and row["variantId"] == variant_id
                     and reusable(row, now, refresh_margin_ms)), None)

    async def commit(self, candidate, now, refresh_margin_ms):
        candidate = parse_record(copy.deepcopy(candidate))
        def update():
            records = self._load()
            for row in records:
                if row["scope"] == candidate["scope"] and row["variantId"] == candidate["variantId"] and reusable(row, now, refresh_margin_ms):
                    return {"record": row, "accepted": False}
            records = [row for row in records if reusable(row, now, refresh_margin_ms)
                       and (row["scope"], row["variantId"]) != (candidate["scope"], candidate["variantId"])]
            self._save(records + [candidate])
            return {"record": copy.deepcopy(candidate), "accepted": True}
        return await with_file_lock(self.path, update)

    async def remove(self, scope, variant_id, file_id):
        def update():
            records = self._load()
            keep = [row for row in records if (row["scope"], row["variantId"], row["fileId"]) != (scope, variant_id, file_id)]
            if len(records) != len(keep):
                self._save(keep)
        await with_file_lock(self.path, update)

    async def clear(self, scope):
        def update():
            records = self._load()
            keep = [row for row in records if row["scope"] != scope]
            if len(records) != len(keep):
                self._save(keep)
        await with_file_lock(self.path, update)
