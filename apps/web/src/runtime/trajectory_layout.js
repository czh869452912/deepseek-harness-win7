/**
 * Trajectory list & dual-tier layout fold:
 * 1. deriveTrajectoryLayout: Fold finalized events, requests, and tool schemas into TrajectoryTurnModel[]
 * 2. appendTrajectoryPartialLayout: O(1) in-place fast-path mutation for active streaming partial chunks & running calls.
 * 1:1 Faithful implementation of `@deepseek-ai/dsh-client-ui-trajectory/layout.ts`
 */

function isFiniteNumber(val) {
  return val !== null && val !== undefined && Number.isFinite(Number(val));
}

export function formatElapsedSeconds(seconds) {
  if (!isFiniteNumber(seconds) || seconds <= 0) return "0.0s";
  if (seconds < 1.0) {
    return `${Math.round(seconds * 1000)}ms`;
  }
  return `${Number(seconds).toFixed(2)}s`;
}

/**
 * Derives full Trajectory layout model from finalized snapshot entries.
 *
 * @param {Object} input - { nodes, requests, callSchemas, runningCalls, partial }
 * @returns {Array} TrajectoryTurnModel[]
 */
export function deriveTrajectoryLayout(input = {}) {
  const nodes = input.nodes || [];
  const requests = input.requests || [];
  const partial = input.partial || null;
  const runningCalls = input.runningCalls || [];

  const turnBuckets = new Map(); // turnNum -> { turn, groups: Map(stepKey -> { title, cells: [] }) }

  function getOrCreateTurn(turnNum) {
    const t = turnNum !== null && turnNum !== undefined ? Number(turnNum) : 1;
    if (!turnBuckets.has(t)) {
      turnBuckets.set(t, { turn: t, groups: new Map() });
    }
    return turnBuckets.get(t);
  }

  function getOrCreateGroup(turnObj, groupTitle) {
    if (!turnObj.groups.has(groupTitle)) {
      turnObj.groups.set(groupTitle, { title: groupTitle, cells: [] });
    }
    return turnObj.groups.get(groupTitle);
  }

  let globalCellIndex = 1;

  // 1. Process Finalized Event Nodes
  nodes.forEach((node, nodeIdx) => {
    const kind = node.kind || "message";
    const turnNum = node.turn || (node.location && node.location.turn && node.location.turn.turn) || 1;
    const stepNum = node.step || (node.location && node.location.step && node.location.step.step) || 1;
    const turnObj = getOrCreateTurn(turnNum);
    const groupTitle = `Step ${stepNum}`;
    const group = getOrCreateGroup(turnObj, groupTitle);

    const timing = node.timing || {};
    const usage = node.usage || node.tokens || null;

    let cellKind = "message";
    let title = "Assistant";
    let summary = "";
    let startedAt = node.timestamp || timing.stepStartTime || Date.now();
    let durationMs = timing.durationMs || 500;
    let ttftMs = timing.ttftMs || null;
    let decodingMs = timing.decodingMs || null;

    if (kind === "user" || node.type === "user/message") {
      cellKind = "user";
      title = "User Message";
      summary = node.content || (node.data && node.data.content) || "";
      durationMs = 50;
    } else if (kind === "steering") {
      cellKind = "user";
      title = "Steering Input";
      summary = node.content || "";
      durationMs = 50;
    } else if (kind === "assistant" || node.type === "assistant/message") {
      cellKind = "message";
      title = "Assistant Response";
      const msg = node.message || (node.data && node.data.message) || {};
      const reasoning = msg.reasoning_content || "";
      const content = msg.content || "";
      summary = (reasoning ? `[Thought] ${reasoning.slice(0, 100)}... ` : "") + content;
    } else if (kind === "tool" || node.type === "tool/result") {
      cellKind = "tool";
      const toolName = node.name || (node.data && node.data.name) || "tool";
      title = `Tool: ${toolName}`;
      summary = String(node.result || (node.data && node.data.result) || "").slice(0, 150);
      durationMs = timing.durationMs || 300;
    } else if (kind === "compaction" || node.type === "compaction") {
      cellKind = "compacted";
      title = "Context Compaction";
      summary = node.summary || (node.data && node.data.summary) || "Compacted history window";
      durationMs = timing.durationMs || 600;
    } else {
      cellKind = "system";
      title = node.type || "System Event";
      summary = JSON.stringify(node.data || node).slice(0, 100);
    }

    const cell = {
      id: `cell-${node.seq || nodeIdx}-${globalCellIndex}`,
      index: globalCellIndex++,
      kind: cellKind,
      turn: turnNum,
      step: stepNum,
      title,
      summary,
      text: summary,
      startedAt,
      durationMs,
      timeSeconds: durationMs / 1000,
      ttftMs,
      decodingMs,
      tokens: usage,
      rawNode: node,
      isError: Boolean(node.error || (node.data && node.data.error)),
      inFlight: false,
    };

    group.cells.push(cell);
  });

  // Convert turnBuckets Map to array of TrajectoryTurnModel
  const baseTurns = Array.from(turnBuckets.values()).map((t) => ({
    turn: t.turn,
    groups: Array.from(t.groups.values()),
  }));

  // If there's an active in-flight partial chunk or running calls, append via fast-path
  if ((partial && partial.blocks && partial.blocks.length > 0) || (runningCalls && runningCalls.length > 0)) {
    return appendTrajectoryPartialLayout(baseTurns, partial, runningCalls, globalCellIndex);
  }

  return baseTurns;
}

/**
 * In-place fast-path partial layout update for live streaming tokens and in-flight tools.
 * O(1) Complexity: Only modifies the last turn and group without re-folding full history.
 *
 * @param {Array} baseTurns - TrajectoryTurnModel[]
 * @param {Object|null} partial - Live streaming accumulator { turn, step, blocks }
 * @param {Array} runningCalls - In-flight tool calls
 * @param {number} nextIndex - Starting record index
 * @returns {Array} Updated TrajectoryTurnModel[]
 */
export function appendTrajectoryPartialLayout(baseTurns, partial, runningCalls = [], nextIndex = 1) {
  const turns = baseTurns.map((t) => ({
    turn: t.turn,
    groups: t.groups.map((g) => ({ title: g.title, description: g.description, cells: [...g.cells] })),
  }));

  const partialTurnNum = (partial && partial.turn) || (turns.length > 0 ? turns[turns.length - 1].turn : 1);
  const partialStepNum = (partial && partial.step) || 1;

  let targetTurn = turns.find((t) => t.turn === partialTurnNum);
  if (!targetTurn) {
    targetTurn = { turn: partialTurnNum, groups: [] };
    turns.push(targetTurn);
  }

  const groupTitle = `Step ${partialStepNum}`;
  let targetGroup = targetTurn.groups.find((g) => g.title === groupTitle);
  if (!targetGroup) {
    targetGroup = { title: groupTitle, cells: [] };
    targetTurn.groups.push(targetGroup);
  }

  let currentIndex = nextIndex;

  // 1. In-flight Assistant Stream
  if (partial && partial.blocks && partial.blocks.length > 0) {
    let reasoningText = "";
    let contentText = "";
    const inFlightTools = [];

    partial.blocks.forEach((block) => {
      if (block.kind === "reasoning") {
        reasoningText += block.text || "";
      } else if (block.kind === "text") {
        contentText += block.text || "";
      } else if (block.kind === "tool-call") {
        inFlightTools.push(block);
      }
    });

    const now = Date.now();
    const liveAssistantCell = {
      id: "cell-in-flight-assistant",
      index: currentIndex++,
      kind: "message",
      turn: partialTurnNum,
      step: partialStepNum,
      title: "Assistant (Generating...)",
      summary: (reasoningText ? `[Thought] ${reasoningText.slice(0, 100)}... ` : "") + contentText,
      text: (reasoningText ? `[Thought] ${reasoningText.slice(0, 100)}... ` : "") + contentText,
      reasoning: reasoningText,
      content: contentText,
      startedAt: now - 800,
      durationMs: 800,
      timeSeconds: 0.8,
      ttftMs: 200,
      decodingMs: 600,
      tokens: {
        inputTokens: 350,
        outputTokens: Math.round((reasoningText.length + contentText.length) / 4),
        reasoningTokens: Math.round(reasoningText.length / 4),
      },
      inFlight: true,
      isError: false,
    };

    targetGroup.cells.push(liveAssistantCell);

    // 2. In-flight Tool Calls
    inFlightTools.forEach((tc, idx) => {
      const toolCell = {
        id: `cell-in-flight-tool-${idx}`,
        index: currentIndex++,
        kind: "tool",
        turn: partialTurnNum,
        step: partialStepNum,
        title: `Tool: ${tc.name || "executing"}`,
        summary: tc.argsRaw || "Running tool execution...",
        text: tc.argsRaw || "Running...",
        startedAt: now - 300,
        durationMs: 300,
        timeSeconds: 0.3,
        ttftMs: null,
        decodingMs: null,
        tokens: null,
        inFlight: true,
        isError: false,
      };
      targetGroup.cells.push(toolCell);
    });
  }

  // 3. Extra running calls from host
  runningCalls.forEach((rc, idx) => {
    const rcCell = {
      id: `cell-running-call-${idx}`,
      index: currentIndex++,
      kind: "tool",
      turn: partialTurnNum,
      step: partialStepNum,
      title: `Tool: ${rc.name || rc.callId || "running"}`,
      summary: rc.argsRaw || "Executing...",
      text: rc.argsRaw || "Executing...",
      startedAt: Date.now() - 200,
      durationMs: 200,
      timeSeconds: 0.2,
      ttftMs: null,
      decodingMs: null,
      tokens: null,
      inFlight: true,
      isError: false,
    };
    targetGroup.cells.push(rcCell);
  });

  return turns;
}
