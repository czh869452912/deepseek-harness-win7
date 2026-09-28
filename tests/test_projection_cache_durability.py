import asyncio
import json

import pytest

from dsh.cordis.context import Context
from dsh.core.session.session import SessionPlugin
from dsh.session.projections import SessionProjectionsPlugin
from dsh.session.projection_cache import SessionProjectionCachePlugin
from dsh.storage.hub import StoragePlugin
from dsh.storage.plugins import StorageJsonPlugin, StorageDomainPlugin


async def composition(root):
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(SessionProjectionsPlugin)
    await ctx.plugin(StoragePlugin)
    await ctx.plugin(StorageJsonPlugin, config={"root": str(root)})
    await ctx.plugin(StorageDomainPlugin, config={"backend": "json"})
    ctx.get("sessionProjections").register({"key": "count", "stateVersion": 1,
        "stateSchema": lambda value: int(value), "init": lambda header: 0,
        "apply": lambda state, event: state + 1, "wire": {"viewSchema": lambda value: int(value), "view": lambda state: state}})
    await ctx.plugin(SessionProjectionCachePlugin, config={"writeEveryEvents": 10, "writeIntervalMs": 5000})
    return ctx


@pytest.mark.asyncio
async def test_checkpoint_reopens_and_recreated_identity_does_not_reuse_it(tmp_path):
    ctx = await composition(tmp_path)
    sessions = ctx.get("sessions")
    session = sessions.create("cache-session", meta={"cwd": str(tmp_path)})
    session.append("test/event", {"value": 1}, ignorable=True)
    cache = ctx.get("sessionProjectionCache")
    await cache.write(session)
    expected = cache.cached_snapshot(session.header)
    assert expected["values"]["count"] == len(session.events)
    document = tmp_path / "session_projcache" / "sessions" / "cache-session.json"
    assert json.loads(document.read_text(encoding="utf-8"))["version"] == 4
    header = session.header
    await ctx.fiber.dispose()
    fresh = await composition(tmp_path)
    try:
        assert fresh.get("sessionProjectionCache").cached_snapshot(header) == expected
        from dsh.core.session import SessionHeader
        replacement = SessionHeader("cache-session", created_at=header.createdAt + 1, cwd=header.cwd)
        assert fresh.get("sessionProjectionCache").cached_snapshot(replacement) is None
    finally:
        await fresh.fiber.dispose()


@pytest.mark.asyncio
async def test_stale_per_record_file_does_not_hide_other_records(tmp_path):
    from dsh.storage.storage_json import JsonStorageBackend
    from dsh.storage.backend import KvUnitDescriptor
    backend = JsonStorageBackend(str(tmp_path))
    unit = await backend.kv.open(KvUnitDescriptor("cache", 4, ["sessions"], layout="per-record"))
    await unit.put_record("sessions", "good", {"value": 1})
    (tmp_path / "cache" / "sessions" / "stale.json").write_text('{"version":3,"record":42}', encoding="utf-8")
    (tmp_path / "cache" / "sessions" / "bad.json").write_text('{broken', encoding="utf-8")
    assert (await unit.load_all())["tables"] == {"sessions": {"good": {"value": 1}}}
    with pytest.raises(ValueError, match="path-safe"):
        await unit.put_record("sessions", "../escape", 1)
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("document", [
    {"unit": None, "tables": {}},
    {"unit": {"name": "cache"}, "tables": ["invalid"]},
    {"unit": {"name": "foreign"}, "tables": {"sessions": {"one": 1}}},
])
async def test_invalid_legacy_cache_is_ignored_and_preserved(tmp_path, document):
    from dsh.storage.storage_json import JsonStorageBackend
    from dsh.storage.backend import KvUnitDescriptor
    path = tmp_path / "cache.json"
    original = json.dumps(document)
    path.write_text(original, encoding="utf-8")
    backend = JsonStorageBackend(str(tmp_path))
    try:
        unit = await backend.kv.open(KvUnitDescriptor("cache", 4, ["sessions"], layout="per-record"))
        assert (await unit.load_all())["tables"] == {"sessions": {}}
        assert path.read_text(encoding="utf-8") == original
        assert not (tmp_path / "cache").exists()
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_cold_session_listing_survives_restart_without_activating_agent(tmp_path):
    from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin
    from dsh.session.listing import SessionListing
    first = await composition(tmp_path / "storage")
    await first.plugin(JsonlSessionPersistencePlugin, config={"root": str(tmp_path / "logs")})
    listing = SessionListing(first)
    session = first.get("sessions").create("stored-session", meta={"cwd": str(tmp_path)})
    session.append("turn/start", {"turn": 1})
    session.append_user_message("hello")
    await first.get("sessionProjectionCache").write(session)
    before = await listing.list()
    assert before[0]["blank"] is False
    await first.fiber.dispose()
    fresh = await composition(tmp_path / "storage")
    await fresh.plugin(JsonlSessionPersistencePlugin, config={"root": str(tmp_path / "logs")})
    try:
        after = await SessionListing(fresh).list()
        assert after == before
        assert fresh.get("sessions").get("stored-session") is None
        assert fresh.get("agents") is None
    finally:
        await fresh.fiber.dispose()

