/**
 * Operation-sequence and recorded-time projections for the Trajectory Overview.
 * 1:1 Faithful implementation of `@deepseek-ai/dsh-client-ui-trajectory/timeline.ts`
 */

/**
 * Lane assignment by Cell Kind:
 * - Lane 0: User / System / Context / Steering / Fallback
 * - Lane 1: Assistant Message / Compaction
 * - Lane 2: Tool Call / Subtool
 */
export function laneForKind(kind) {
  if (kind === "tool" || kind === "subtool") return 2;
  if (kind === "message" || kind === "compacted" || kind === "assistant") return 1;
  return 0;
}

function isFiniteNumber(val) {
  return val !== null && val !== undefined && Number.isFinite(Number(val));
}

export function formatTimelineOffset(milliseconds) {
  if (!isFiniteNumber(milliseconds) || milliseconds < 0) return "0ms";
  if (milliseconds >= 60000) {
    const mins = Math.floor(milliseconds / 60000);
    const secs = ((milliseconds % 60000) / 1000).toFixed(1);
    return `${mins}m ${secs}s`;
  }
  if (milliseconds >= 1000) {
    return `${(milliseconds / 1000).toFixed(2)}s`;
  }
  return `${Math.round(milliseconds)}ms`;
}

function cellTimeRange(cell) {
  const startedAt = Number(cell.startedAt);
  if (!isFiniteNumber(startedAt)) return null;

  let durationMs = 0;
  if (isFiniteNumber(cell.durationMs)) {
    durationMs = Math.max(0, Number(cell.durationMs));
  } else if (isFiniteNumber(cell.timeSeconds)) {
    durationMs = Math.max(0, Number(cell.timeSeconds) * 1000);
  }

  return {
    start: startedAt,
    end: startedAt + durationMs,
    startedAt,
    durationMs,
  };
}

/**
 * Project visible records into a stable 3-lane timeline model.
 * Modes:
 * - 'sequence': Equal step spacing along X-axis
 * - 'duration': Real duration along X-axis with idle wait time compressed
 * - 'time': Absolute timestamp along X-axis with idle wait time compressed
 * - 'actual': Real wall-clock timestamp along X-axis without compressing idle time
 *
 * @param {Array} turns - TrajectoryTurnModel[]
 * @param {'sequence'|'duration'|'time'|'actual'} mode
 * @returns {Object|null} TimelineModel: { start, end, spans, turnBoundaries, totalMs }
 */
export function deriveTrajectoryTimeline(turns, mode = "duration") {
  if (!turns || turns.length === 0) return null;

  if (mode !== "sequence") {
    return deriveTimedTimeline(
      turns,
      mode === "duration" || mode === "actual",
      mode === "duration" || mode === "time"
    );
  }

  // 1. 'sequence' mode
  const spans = [];
  const turnBoundaries = [];

  for (const turn of turns) {
    const cells = (turn.groups || []).flatMap((g) =>
      (g.cells || []).filter((c) => c.requestOnly !== true)
    );
    if (cells.length === 0) continue;

    if (turn.turn !== null && turn.turn !== undefined) {
      turnBoundaries.push({
        turn: turn.turn,
        time: spans.length,
      });
    }

    cells.forEach((cell, offset) => {
      const idx = spans.length + offset;
      spans.push({
        start: idx,
        end: idx + 1,
        index: cell.index,
        id: cell.id || `span-${idx}`,
        isError: cell.isError === true,
        kind: cell.kind || "message",
        label: cell.title || cell.text || "",
        lane: laneForKind(cell.kind),
        ttftMs: cell.ttftMs || null,
        decodingMs: cell.decodingMs || null,
        durationMs: cell.durationMs || null,
        startedAt: cell.startedAt || null,
        inFlight: Boolean(cell.inFlight),
        cell,
      });
    });
  }

  if (spans.length === 0) return null;

  return {
    start: 0,
    end: spans.length,
    total: spans.length,
    totalMs: spans.length,
    spans,
    turnBoundaries,
    mode: "sequence",
  };
}

/**
 * Timed projection with idle gap compression.
 */
function deriveTimedTimeline(turns, actualDuration, compressIdle) {
  const timedTurns = [];

  for (const turn of turns) {
    const rawSpans = [];
    for (const group of turn.groups || []) {
      for (const cell of group.cells || []) {
        if (cell.requestOnly === true) continue;
        const range = cellTimeRange(cell);
        if (range === null) continue;

        rawSpans.push({
          start: range.start,
          end: range.end,
          index: cell.index,
          id: cell.id || `span-${cell.index}`,
          isError: cell.isError === true,
          kind: cell.kind || "message",
          label: cell.title || cell.text || "",
          lane: laneForKind(cell.kind),
          ttftMs: cell.ttftMs || null,
          decodingMs: cell.decodingMs || null,
          durationMs: range.durationMs,
          startedAt: range.startedAt,
          inFlight: Boolean(cell.inFlight),
          cell,
        });
      }
    }

    if (rawSpans.length > 0) {
      timedTurns.push({ turn: turn.turn, rawSpans });
    }
  }

  const allRawSpans = timedTurns.flatMap((t) => t.rawSpans);
  if (allRawSpans.length === 0) return null;

  // Compute idle gaps to compress
  const removedIdleBySpan = new Map();
  let removedIdle = 0;
  let coveredUntil = null;

  const sortedSpans = [...allRawSpans].sort(
    (a, b) => a.start - b.start || a.end - b.end
  );

  for (const span of sortedSpans) {
    if (compressIdle && coveredUntil !== null && span.start > coveredUntil + 300) {
      removedIdle += span.start - (coveredUntil + 300);
    }
    removedIdleBySpan.set(span, removedIdle);
    coveredUntil = coveredUntil === null ? span.end : Math.max(coveredUntil, span.end);
  }

  const spans = [];
  const turnBoundaries = [];

  for (const t of timedTurns) {
    const projected = t.rawSpans.map((span) => {
      const offset = removedIdleBySpan.get(span) || 0;
      const start = span.start - offset;
      const end = (actualDuration ? span.end : span.start + Math.max(10, span.durationMs)) - offset;
      return {
        ...span,
        start,
        end: Math.max(start + 1, end),
      };
    });

    spans.push(...projected);

    if (t.turn !== null && t.turn !== undefined && projected.length > 0) {
      turnBoundaries.push({
        turn: t.turn,
        time: Math.min(...projected.map((s) => s.start)),
      });
    }
  }

  const minTime = Math.min(...spans.map((s) => s.start));
  const maxTime = Math.max(...spans.map((s) => s.end));
  const totalMs = Math.max(10, maxTime - minTime);

  return {
    start: minTime,
    end: maxTime,
    total: totalMs,
    totalMs,
    spans,
    turnBoundaries,
    mode: compressIdle ? "duration" : "actual",
  };
}

/**
 * Returns a Set of record indexes active within the selected time range.
 */
export function trajectoryTimelineFocusIndexes(turns, range, mode = "duration") {
  const model = deriveTrajectoryTimeline(turns, mode);
  if (!model || !range) return new Set();

  return new Set(
    model.spans
      .filter((s) => s.start <= range.end && s.end >= range.start)
      .map((s) => s.index)
  );
}
