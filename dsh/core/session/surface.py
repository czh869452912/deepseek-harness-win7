"""
Surface layer on top of the session event log: an ordered view of events
that produce LLM messages. The append-only log remains the source of truth.
Ported 1:1 from reference packages/core/session/src/surface.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from dsh.core.surface import (
    SURFACE_EVENT_TYPES,
    SurfaceFoldReplacement,
    SurfaceFoldResult,
    SurfaceManager,
    SurfacePlan,
    derive_event_message,
    fold_surface,
    is_append_surface_event,
    is_replacement_surface_event,
    is_surface_eligible_type,
    is_surface_event,
    tool_pairing_balanced_after,
    tool_pairing_balanced_before,
)

# CamelCase aliases 1:1 with reference
isSurfaceEligibleType = is_surface_eligible_type
isSurfaceEvent = is_surface_event
isAppendSurfaceEvent = is_append_surface_event
isReplacementSurfaceEvent = is_replacement_surface_event
deriveEventMessage = derive_event_message
foldSurface = fold_surface
