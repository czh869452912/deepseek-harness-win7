"""
Session-log snapshot support package.
Ported 1:1 from reference packages/test-support/session-snapshot.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from .chunk_rows import decode_storage_record, is_chunk_row, pack_chunk_runs
from .identity import redactSessionSnapshotIds
from .manifest import parseSnapshotManifest, parse_snapshot_manifest
from .normalize import (
    extractSnapshotSpillPaths,
    normalizeSessionLog,
    normalizeSessionSnapshot,
    normalizeSessionSnapshots,
    normalizeStdout,
    scrubRequestHeaders,
    scrubSessionSnapshot,
    scrubSystemPrompts,
    scrubToolSchemas,
    tokenizeSessionFixtureCwd,
)
from .seq_ranges import decode_seq_ranges, encode_seq_ranges
from .workspace import (
    EMPTY_WORKSPACE_MARKER,
    captureExpectedWorkspaceSnapshot,
    captureWorkspaceSnapshot,
)

__all__ = [
    "redactSessionSnapshotIds",
    "parseSnapshotManifest",
    "parse_snapshot_manifest",
    "captureWorkspaceSnapshot",
    "captureExpectedWorkspaceSnapshot",
    "EMPTY_WORKSPACE_MARKER",
    "extractSnapshotSpillPaths",
    "normalizeStdout",
    "normalizeSessionLog",
    "normalizeSessionSnapshot",
    "normalizeSessionSnapshots",
    "scrubRequestHeaders",
    "scrubSessionSnapshot",
    "scrubSystemPrompts",
    "scrubToolSchemas",
    "tokenizeSessionFixtureCwd",
    "encode_seq_ranges",
    "decode_seq_ranges",
    "pack_chunk_runs",
    "decode_storage_record",
    "is_chunk_row",
]
