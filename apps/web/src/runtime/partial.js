/**
 * DeepSeek Harness PartialAccumulator (`@deepseek-ai/dsh-client-runtime/sessions/partial`)
 * Real-time assistant/chunk stream accumulator:
 * Folds the StreamChunk variants into block-level immutable AssistantBlock[] projections.
 */

export function isVisibleAssistantChunk(type) {
  return (
    type === "block-start" ||
    type === "text-delta" ||
    type === "reasoning-delta" ||
    type === "tool-call-delta" ||
    type === "block-end" ||
    type === "assistant/chunk" ||
    type === "session/chunk"
  );
}

export function emptyAssistantBlock(blockType) {
  switch (blockType) {
    case "text":
      return { kind: "text", text: "" };
    case "reasoning":
      return { kind: "reasoning", text: "" };
    case "tool-call":
      return { kind: "tool-call", callId: "", name: "", argsRaw: "" };
    default:
      return { kind: "other", block: null };
  }
}

export class PartialAccumulator {
  constructor(turn = 1, step = 1, initialBlocks = []) {
    this.turn = turn;
    this.step = step;
    this.blocks = [...initialBlocks];
    this.changed = true;
    this.snapshot = { turn, step, blocks: initialBlocks };
  }

  /**
   * Fold one incoming stream chunk.
   */
  push(chunk) {
    if (!chunk) return false;

    // 1. Handle official typed StreamChunk variants
    if (chunk.type === "block-start") {
      const idx = chunk.index !== undefined ? chunk.index : this.blocks.length;
      this.blocks[idx] = emptyAssistantBlock(chunk.blockType || "text");
      this.changed = true;
      return true;
    }

    if (chunk.type === "text-delta") {
      const idx = chunk.index !== undefined ? chunk.index : 0;
      const prev = this.blocks[idx];
      const prevText = prev && prev.kind === "text" ? prev.text : "";
      this.blocks[idx] = { kind: "text", text: prevText + (chunk.text || "") };
      this.changed = true;
      return true;
    }

    if (chunk.type === "reasoning-delta") {
      const idx = chunk.index !== undefined ? chunk.index : 0;
      const prev = this.blocks[idx];
      const prevText = prev && prev.kind === "reasoning" ? prev.text : "";
      this.blocks[idx] = { kind: "reasoning", text: prevText + (chunk.text || "") };
      this.changed = true;
      return true;
    }

    if (chunk.type === "tool-call-delta") {
      const idx = chunk.index !== undefined ? chunk.index : this.blocks.length;
      const prev = this.blocks[idx];
      const base =
        prev && prev.kind === "tool-call"
          ? prev
          : { kind: "tool-call", callId: "", name: "", argsRaw: "" };
      this.blocks[idx] = {
        kind: "tool-call",
        callId: chunk.id || base.callId || `call-${idx}`,
        name: chunk.name !== undefined ? chunk.name : base.name,
        argsRaw: base.argsRaw + (chunk.argumentsDelta || chunk.arguments || ""),
      };
      this.changed = true;
      return true;
    }

    if (chunk.type === "block-end") {
      const idx = chunk.index !== undefined ? chunk.index : 0;
      if (chunk.block) {
        this.blocks[idx] = chunk.block;
      }
      this.changed = true;
      return true;
    }

    // 2. Handle unified/legacy HTTP proxy chunk envelope
    const deltaType = chunk.delta_type || chunk.type;

    if (deltaType === "reasoning" || chunk.reasoning !== undefined) {
      let reasoningBlock = this.blocks.find((b) => b && b.kind === "reasoning");
      if (!reasoningBlock) {
        reasoningBlock = { kind: "reasoning", text: "" };
        this.blocks.unshift(reasoningBlock);
      }
      reasoningBlock.text = chunk.reasoning !== undefined ? chunk.reasoning : (reasoningBlock.text + (chunk.delta || ""));
      this.changed = true;
      return true;
    }

    if (deltaType === "text" || chunk.content !== undefined) {
      let textBlock = this.blocks.find((b) => b && b.kind === "text");
      if (!textBlock) {
        textBlock = { kind: "text", text: "" };
        this.blocks.push(textBlock);
      }
      textBlock.text = chunk.content !== undefined ? chunk.content : (textBlock.text + (chunk.delta || ""));
      this.changed = true;
      return true;
    }

    if (deltaType === "tool_call" || chunk.tool_calls) {
      const toolCalls = chunk.tool_calls || [];
      // Replace or update tool-call blocks
      this.blocks = this.blocks.filter((b) => b && b.kind !== "tool-call");
      toolCalls.forEach((tc, i) => {
        const fn = tc.function || {};
        this.blocks.push({
          kind: "tool-call",
          callId: tc.id || `call-${i}`,
          name: fn.name || "",
          argsRaw: fn.arguments || "",
        });
      });
      this.changed = true;
      return true;
    }

    return false;
  }

  /**
   * Produce immutable snapshot of the partial assistant output.
   */
  toPartial() {
    if (this.changed) {
      this.snapshot = {
        turn: this.turn,
        step: this.step,
        blocks: this.blocks.filter((b) => b !== undefined),
      };
      this.changed = false;
    }
    return this.snapshot;
  }

  clear() {
    this.blocks = [];
    this.changed = true;
    this.snapshot = { turn: this.turn, step: this.step, blocks: [] };
  }
}
