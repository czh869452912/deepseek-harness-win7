from dsh.session.persistence import (
    SessionInspection,
    SessionLocation,
    SessionPersistence,
    SessionPersistenceSnapshot,
)
from dsh.session.persistence_jsonl import JsonlSessionPersistence, JsonlSessionPersistencePlugin
from dsh.session.persistence_sqlite import SqliteSessionPersistence, SqliteSessionPersistencePlugin
from dsh.session.projections import (
    ProjectionDefinition,
    SessionProjectionRegistry,
    SessionProjectionsPlugin,
)
from dsh.session.repair import interrupted_turn_closers, migrate_legacy_event
from dsh.session.session_query import SessionQueryPlugin, SessionQueryService, extract_session_event_text
from dsh.session.stats import SessionStatsPlugin, SessionStatsProjection
from dsh.session.title import SessionTitlePlugin, SessionTitleService, fallback_session_title, normalize_session_title

__all__ = [
    "SessionLocation",
    "SessionInspection",
    "SessionPersistenceSnapshot",
    "SessionPersistence",
    "JsonlSessionPersistence",
    "JsonlSessionPersistencePlugin",
    "SqliteSessionPersistence",
    "SqliteSessionPersistencePlugin",
    "ProjectionDefinition",
    "SessionProjectionRegistry",
    "SessionProjectionsPlugin",
    "interrupted_turn_closers",
    "migrate_legacy_event",
    "SessionQueryService",
    "SessionQueryPlugin",
    "extract_session_event_text",
    "SessionStatsProjection",
    "SessionStatsPlugin",
    "SessionTitleService",
    "SessionTitlePlugin",
    "fallback_session_title",
    "normalize_session_title",
]
