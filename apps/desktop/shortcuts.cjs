/* Generated from DeepSeek Harness 38a6a5c965aa99ab525161efb7cc5cf1fe62fced by scripts/build_desktop_shortcuts.mjs. */
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// reference/apps/desktop/src/keyboard.ts
var keyboard_exports = {};
__export(keyboard_exports, {
  installDesktopShortcuts: () => installDesktopShortcuts
});
module.exports = __toCommonJS(keyboard_exports);
var import_electron = require("electron");

// reference/packages/client/shortcuts/src/binding.ts
var keyNames = {
  Slash: "/",
  Comma: ",",
  Period: ".",
  Backslash: "\\",
  Backquote: "`",
  Minus: "-",
  Equal: "=",
  BracketLeft: "[",
  BracketRight: "]",
  Semicolon: ";",
  Quote: "'",
  Enter: "Enter",
  Escape: "Esc",
  Space: "Space",
  Tab: "Tab",
  Backspace: "Backspace",
  Delete: "Delete",
  ArrowUp: "\u2191",
  ArrowDown: "\u2193",
  ArrowLeft: "\u2190",
  ArrowRight: "\u2192"
};
var modifierOrder = ["control", "alt", "shift", "meta"];
function normalizeBinding(binding, platform) {
  const codes = [binding.code, ...binding.secondCode === void 0 ? [] : [binding.secondCode]];
  codes.sort();
  for (const code of codes) {
    if (!/^(Key[A-Z]|Digit[0-9]|F([1-9]|1[0-9]|2[0-4]))$/u.test(code) && !Object.hasOwn(keyNames, code)) throw new Error(`Unsupported shortcut code: ${code}`);
  }
  if (codes.length === 2 && codes[0] === codes[1]) throw new Error("Shortcut keys must be distinct");
  const modifiers = new Set(binding.modifiers.map((value) => value === "primary" ? platform === "macos" ? "meta" : "control" : value));
  return {
    code: codes[0],
    ...codes[1] === void 0 ? {} : { secondCode: codes[1] },
    modifiers: modifierOrder.filter((value) => modifiers.has(value))
  };
}
function bindingKey(binding) {
  const codes = binding.secondCode === void 0 ? [binding.code] : [binding.code, binding.secondCode].sort();
  return [...binding.modifiers, ...codes].join("+");
}
function presentBinding(binding, platform) {
  if (binding === null) return { keys: [], aria: void 0 };
  const key = keyNames[binding.code] ?? binding.code.replace(/^(Key|Digit)/u, "");
  const symbols = platform === "macos" ? { control: "\u2303", alt: "\u2325", shift: "\u21E7", meta: "\u2318" } : { control: "Ctrl", alt: "Alt", shift: "Shift", meta: "Meta" };
  const ariaNames = { control: "Control", alt: "Alt", shift: "Shift", meta: "Meta" };
  const ariaKey = binding.code === "Space" ? "Space" : binding.code === "Escape" ? "Escape" : binding.code.startsWith("Arrow") ? binding.code : key;
  const second = binding.secondCode === void 0 ? [] : [keyNames[binding.secondCode] ?? binding.secondCode.replace(/^(Key|Digit)/u, "")];
  const keys = [...binding.modifiers.map((value) => symbols[value]), key];
  return {
    keys: [...platform === "windows" ? keys.flatMap((label, index) => index === 0 ? [label] : ["+", label]) : keys, ...second],
    aria: binding.secondCode === void 0 ? [...binding.modifiers.map((value) => ariaNames[value]), ariaKey].join("+") : void 0
  };
}
function isWebBindingAllowed(binding, platform) {
  if (binding.secondCode !== void 0) return false;
  if (platform === "windows" || platform === "macos") {
    if (binding.modifiers.length >= 3) return true;
    const primary = platform === "macos" ? "meta" : "control";
    if (binding.modifiers.length === 1 && (["Comma", "Backslash"].includes(binding.code) && binding.modifiers[0] === primary || binding.code === "Backquote" && binding.modifiers[0] === "control")) return true;
    if (binding.modifiers.length === 2 && binding.modifiers.includes(primary) && (binding.modifiers.includes("alt") || binding.modifiers.includes("shift"))) return true;
  }
  return [
    { code: "Slash", modifiers: ["primary"] },
    { code: "Comma", modifiers: ["primary", "shift"] },
    { code: "Period", modifiers: ["primary", "shift"] }
  ].some((candidate) => bindingKey(binding) === bindingKey(normalizeBinding(candidate, platform)));
}

// reference/packages/util/values/lib/index.js
var SIMPLE_ESCAPES = {
  '"': '"',
  "\\": "\\",
  "/": "/",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "	"
};
var CONTENT_ESCAPE = /[\\\u0000-\u001f]/u;
function isWhitespace(c) {
  return c === " " || c === "\n" || c === "\r" || c === "	";
}
function isHex(c) {
  return c >= "0" && c <= "9" || c >= "a" && c <= "f" || c >= "A" && c <= "F";
}
var PartialArguments = class PartialArguments2 {
  /** The view of a call with no arguments available. */
  static EMPTY = PartialArguments2.fromObject({});
  /**
  * View finished argument text without scanning it until a reader asks.
  * @param text - the complete argument JSON text.
  * @returns a sealed view.
  */
  static fromText(text) {
    const view = new PartialArguments2();
    view.append(text);
    view.sealed = true;
    return view;
  }
  /**
  * View an already parsed argument payload, such as a PTC dispatch object.
  * @param value - the parsed argument value.
  * @returns a sealed view; a non-object payload has no fields.
  */
  static fromObject(value) {
    const view = new PartialArguments2();
    view.object = typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
    view.sealed = true;
    return view;
  }
  /**
  * The source: text so far or a parsed object, plus whether it can still grow.
  * These are the only enumerable fields, so two views over the same source
  * compare equal structurally however far each has been read.
  */
  chunks = [];
  object;
  sealed = false;
  #ends = [];
  #size = 0;
  #consumed = 0;
  #mode = "root";
  #escape = false;
  #keyStart = 0;
  #keyEscaped = false;
  #key = "";
  #current = null;
  #nestedEnds = [];
  #nestedInString = false;
  #invalidAt;
  #invalidValue = false;
  #entries = /* @__PURE__ */ new Map();
  #order = [];
  #reads = /* @__PURE__ */ new Map();
  /** Whether this view rejects further appends; does not scan text or register reads. */
  get isSealed() {
    return this.sealed;
  }
  /** Whether indexing or a content read found invalid JSON; unread value contents are not validated. */
  get invalid() {
    this.scan();
    return this.#mode === "invalid" || this.#invalidValue;
  }
  /**
  * Retain streamed argument text without scanning or comparing observed answers.
  * @param fragment - the text following every fragment appended before.
  */
  append(fragment) {
    if (this.sealed) throw new Error("PartialArguments: cannot append to a sealed view");
    if (fragment.length === 0) return;
    this.chunks.push(fragment);
    this.#size += fragment.length;
    this.#ends.push(this.#size);
  }
  /**
  * Reconcile a streamed prefix with authoritative complete text without joining the fragments.
  * @param text - the final argument text, which replaces missing or conflicting deltas.
  * @returns this view sealed with its caches retained when every character matches; otherwise a new sealed view.
  */
  settle(text) {
    if (this.object !== void 0 || text.length !== this.#size) return PartialArguments2.fromText(text);
    let offset = 0;
    for (const chunk of this.chunks) {
      if (!text.startsWith(chunk, offset)) return PartialArguments2.fromText(text);
      offset += chunk.length;
    }
    this.chunks = text.length === 0 ? [] : [text];
    this.#ends = text.length === 0 ? [] : [text.length];
    this.sealed = true;
    return this;
  }
  /**
  * Compare observed answers and advance their publication baseline. Unread views remain unscanned.
  * @returns whether any observed answer changed since its first read or the preceding refresh.
  */
  refresh() {
    if (this.#reads.size === 0) return false;
    this.scan();
    let changed = false;
    let completions = false;
    for (const read of this.#reads.values()) {
      if (read.completion) {
        completions = true;
        continue;
      }
      changed = this.refreshRead(read) || changed;
    }
    if (completions) {
      for (const read of this.#reads.values()) if (read.completion) changed = this.refreshRead(read) || changed;
    }
    if (this.sealed) this.#reads.clear();
    return changed;
  }
  refreshRead(read) {
    const now = read.answer();
    if (Object.is(now, read.last)) return false;
    read.last = now;
    return true;
  }
  /**
  * Check whether no further fields can arrive.
  * @returns whether the outer object closed, indexing failed, or the view is sealed; unread values are not validated.
  */
  closed() {
    return this.remember("closed", "", () => this.closedNow());
  }
  /**
  * List discovered fields in first-appearance order.
  * @returns top-level keys seen so far, in first-appearance order.
  */
  keys() {
    return this.remember("keys", "", () => this.keysNow(), (keys) => keys.length);
  }
  /**
  * Check whether a top-level field has appeared.
  * @param key - argument name.
  * @returns whether the field has appeared (a string opened or another value began).
  */
  has(key) {
    return this.remember("has", key, () => this.hasNow(key));
  }
  /**
  * Check whether a field's closing delimiter has arrived, without validating its contents.
  * @param key - argument name.
  * @returns whether its delimiter arrived and no content reader has reported an error for this value.
  */
  complete(key) {
    return this.remember("complete", key, () => this.completeNow(key));
  }
  /**
  * Read string length without materializing its text.
  * @param key - argument name.
  * @param options - change granularity for a streaming string.
  * @returns decoded UTF-16 length of the string field so far; undefined when absent or not a string.
  */
  stringLength(key, options) {
    const step = Math.max(1, Math.floor(options?.step ?? 1));
    const offset = options?.offset ?? 0;
    return this.remember(`length:${step}:${offset}`, key, () => this.lengthNow(key), (length) => length === void 0 ? void 0 : Math.ceil((length + offset) / step));
  }
  /**
  * Check a string against a decoded UTF-16 length limit without materializing it.
  * @param key - argument name.
  * @param maxLength - decoded UTF-16 limit, floored to at least zero.
  * @returns whether the string is longer than the limit; false when absent or not a string.
  */
  stringExceeds(key, maxLength) {
    const limit = Math.max(0, Math.floor(maxLength));
    return this.remember(`exceeds:${limit}`, key, () => (this.lengthNow(key, limit + 1) ?? 0) > limit);
  }
  /**
  * Read a decoded string, including a streaming prefix.
  * @param key - argument name.
  * @returns the string field's decoded text so far; undefined when absent or not a string.
  */
  text(key) {
    return this.remember("text", key, () => this.textNow(key));
  }
  /**
  * Read at most the first decoded UTF-16 units of a string.
  * @param key - argument name.
  * @param maxLength - maximum decoded UTF-16 length, floored to at least one.
  * @returns the bounded string prefix; undefined when absent or not a string.
  */
  textPrefix(key, maxLength) {
    const limit = Math.max(1, Math.floor(maxLength));
    return this.remember(`prefix:${limit}`, key, () => this.textPrefixNow(key, limit));
  }
  /**
  * Read a completed non-string argument.
  * @param key - argument name.
  * @returns the parsed non-string value once it closed; undefined while open, absent, or a string.
  */
  value(key) {
    return this.remember("value", key, () => this.valueNow(key));
  }
  /** Answer a question and, on a streaming view, remember it for change detection. */
  remember(kind, key, read, comparison) {
    this.scan();
    const result = read();
    if (!this.sealed) {
      const id = `${kind}/${key}`;
      if (!this.#reads.has(id)) this.#reads.set(id, {
        completion: kind === "complete",
        answer: comparison === void 0 ? read : () => comparison(read()),
        last: comparison === void 0 ? result : comparison(result)
      });
    }
    return result;
  }
  closedNow() {
    return this.sealed || this.#mode === "closed" || this.#mode === "invalid";
  }
  keysNow() {
    return this.object === void 0 ? this.#order : Object.keys(this.object);
  }
  hasNow(key) {
    return this.object === void 0 ? this.#entries.has(key) : Object.hasOwn(this.object, key);
  }
  completeNow(key) {
    if (this.object !== void 0) return Object.hasOwn(this.object, key);
    const entry = this.#entries.get(key);
    return entry !== void 0 && entry.end >= 0 && (entry.kind === "string" ? entry.invalidAt === void 0 : !entry.invalid);
  }
  lengthNow(key, limit = Number.POSITIVE_INFINITY) {
    if (this.object !== void 0) {
      const field = Object.hasOwn(this.object, key) ? this.object[key] : void 0;
      return typeof field === "string" ? field.length : void 0;
    }
    const entry = this.#entries.get(key);
    if (entry?.kind !== "string") return void 0;
    if (entry.text !== void 0 && entry.text.at === entry.end) return entry.text.length;
    const read = entry.length ??= {
      at: entry.start,
      length: 0,
      text: ""
    };
    this.readString(entry, read, limit, false);
    return read.length;
  }
  textNow(key) {
    if (this.object !== void 0) {
      const field = Object.hasOwn(this.object, key) ? this.object[key] : void 0;
      return typeof field === "string" ? field : void 0;
    }
    const entry = this.#entries.get(key);
    if (entry?.kind !== "string") return void 0;
    if (entry.text === void 0 && entry.end >= 0 && entry.needsDecoding && entry.invalidAt === void 0) {
      let text;
      try {
        text = JSON.parse(`"${this.slice(entry.start, entry.end)}"`);
      } catch (_error) {
      }
      if (text !== void 0) entry.text = {
        at: entry.end,
        length: text.length,
        text
      };
    }
    const read = entry.text ??= {
      at: entry.start,
      length: 0,
      text: ""
    };
    this.readString(entry, read, Number.POSITIVE_INFINITY, true);
    return read.text;
  }
  textPrefixNow(key, maxLength) {
    if (this.object !== void 0) {
      const field = Object.hasOwn(this.object, key) ? this.object[key] : void 0;
      return typeof field === "string" ? field.slice(0, maxLength) : void 0;
    }
    const entry = this.#entries.get(key);
    if (entry?.kind !== "string") return void 0;
    const prefixes = entry.prefixes ??= /* @__PURE__ */ new Map();
    let read = prefixes.get(maxLength);
    if (read === void 0) {
      read = {
        at: entry.start,
        length: 0,
        text: ""
      };
      prefixes.set(maxLength, read);
    }
    this.readString(entry, read, maxLength, true);
    return read.text;
  }
  valueNow(key) {
    if (this.object !== void 0) {
      if (!Object.hasOwn(this.object, key)) return void 0;
      const field = this.object[key];
      return typeof field === "string" ? void 0 : field;
    }
    const entry = this.#entries.get(key);
    if (entry?.kind !== "value" || entry.end < 0 || entry.invalid) return void 0;
    if (entry.parsed === void 0) try {
      entry.parsed = JSON.parse(this.slice(entry.start, entry.end));
    } catch (_error) {
      entry.invalid = true;
      this.#invalidValue = true;
    }
    return entry.parsed;
  }
  chunkAt(at) {
    let low = 0;
    let high = this.#ends.length;
    while (low < high) {
      const mid = low + high >>> 1;
      if (this.#ends[mid] <= at) low = mid + 1;
      else high = mid;
    }
    return low;
  }
  /** Materialize only a requested range, never the cumulative source. */
  slice(start, end) {
    if (start >= end) return "";
    const first = this.chunkAt(start);
    const last = this.chunkAt(end - 1);
    const base = first === 0 ? 0 : this.#ends[first - 1];
    if (first === last) return this.chunks[first].slice(start - base, end - base);
    const parts = [this.chunks[first].slice(start - base)];
    for (let i = first + 1; i < last; i++) parts.push(this.chunks[i]);
    parts.push(this.chunks[last].slice(0, end - this.#ends[last - 1]));
    return parts.join("");
  }
  readString(entry, read, limit, materialize) {
    const end = Math.min(entry.end < 0 ? this.#consumed : entry.end, entry.invalidAt ?? Number.POSITIVE_INFINITY, this.#invalidAt ?? Number.POSITIVE_INFINITY);
    if (!entry.needsDecoding) {
      const length = Math.min(end - read.at, limit - read.length);
      if (length <= 0) return;
      if (materialize) read.text += this.slice(read.at, read.at + length);
      read.at += length;
      read.length += length;
      return;
    }
    let chunkIndex = this.chunkAt(read.at);
    while (read.at < end && read.length < limit) {
      const base = chunkIndex === 0 ? 0 : this.#ends[chunkIndex - 1];
      const chunk = this.chunks[chunkIndex];
      const remaining = chunk.slice(read.at - base, Math.min(chunk.length, end - base));
      const boundary = remaining.search(CONTENT_ESCAPE);
      const length = Math.min(boundary < 0 ? remaining.length : boundary, limit - read.length);
      if (length > 0) {
        if (materialize) read.text += remaining.slice(0, length);
        read.at += length;
        read.length += length;
        if (read.at === base + chunk.length) chunkIndex++;
        continue;
      }
      const type = remaining.length > 1 ? remaining[1] : read.at + 1 < end ? this.chunks[chunkIndex + 1][0] : void 0;
      let decoded;
      let width = 2;
      if (remaining[0] === "\\" && type === void 0 && entry.end < 0) return;
      if (remaining[0] === "\\" && type === "u") {
        const hex = this.slice(read.at + 2, Math.min(end, read.at + 6));
        let valid = true;
        for (let i = 0; i < hex.length; i++) if (!isHex(hex[i])) valid = false;
        if (valid) {
          if (hex.length < 4 && entry.end < 0) return;
          if (hex.length === 4) decoded = String.fromCharCode(Number.parseInt(hex, 16));
        }
        width = 6;
      } else if (remaining[0] === "\\" && type !== void 0) decoded = SIMPLE_ESCAPES[type];
      if (decoded === void 0) {
        entry.invalidAt = read.at;
        this.#invalidValue = true;
        return;
      }
      if (materialize) read.text += decoded;
      read.length++;
      read.at += width;
      while (chunkIndex < this.chunks.length && read.at >= this.#ends[chunkIndex]) chunkIndex++;
    }
  }
  /** Locate new field ranges without decoding or parsing their contents. */
  scan() {
    if (this.object !== void 0 || this.#consumed === this.#size) return;
    for (let i = this.chunkAt(this.#consumed); i < this.chunks.length && this.#invalidAt === void 0; i++) {
      const pending = this.chunks[i];
      const base = i === 0 ? 0 : this.#ends[i - 1];
      for (let index = this.#consumed - base; index < pending.length && this.#mode !== "invalid"; index++) {
        if (this.#mode === "string" || this.#mode === "nested" && this.#nestedInString) {
          const end = this.stringBoundary(pending, index);
          this.#consumed += end - index;
          index = end;
          if (index === pending.length) break;
        }
        this.step(pending[index], this.#consumed);
        this.#consumed++;
      }
    }
  }
  /** Only raw quotes and their preceding backslash runs can terminate a string. */
  stringBoundary(fragment, start) {
    let at = start;
    while (true) {
      const quote = fragment.indexOf('"', at);
      const end = quote < 0 ? fragment.length : quote;
      if (this.#mode === "string") {
        const entry = this.#current;
        if (!entry.needsDecoding && CONTENT_ESCAPE.test(fragment.slice(at, end))) entry.needsDecoding = true;
      }
      let slashStart = end;
      while (slashStart > at && fragment[slashStart - 1] === "\\") slashStart--;
      const escaped = (end - slashStart) % 2 === 1 !== (slashStart === at && this.#escape);
      this.#escape = quote < 0 && escaped;
      if (quote < 0 || !escaped) return end;
      at = quote + 1;
    }
  }
  step(c, at) {
    switch (this.#mode) {
      case "root":
        if (isWhitespace(c)) return;
        if (c === "{") {
          this.#mode = "key-or-end";
          return;
        }
        this.fail();
        return;
      case "key-or-end":
        if (isWhitespace(c)) return;
        if (c === "}") {
          this.#mode = "closed";
          return;
        }
        if (c === '"') {
          this.beginKey(at);
          return;
        }
        this.fail();
        return;
      case "key-only":
        if (isWhitespace(c)) return;
        if (c === '"') {
          this.beginKey(at);
          return;
        }
        this.fail();
        return;
      case "key":
        this.stepKey(c, at);
        return;
      case "colon":
        if (isWhitespace(c)) return;
        if (c === ":") {
          this.#mode = "value";
          return;
        }
        this.fail();
        return;
      case "value":
        this.beginValue(c, at);
        return;
      case "string": {
        const entry = this.#current;
        entry.end = at;
        this.#current = null;
        this.#mode = "comma-or-end";
        return;
      }
      case "scalar":
        this.stepScalar(c, at);
        return;
      case "nested":
        this.stepNested(c, at);
        return;
      case "comma-or-end":
        if (isWhitespace(c)) return;
        if (c === ",") {
          this.#mode = "key-only";
          return;
        }
        if (c === "}") {
          this.#mode = "closed";
          return;
        }
        this.fail();
        return;
      case "closed":
        if (isWhitespace(c)) return;
        this.fail();
        return;
      /* v8 ignore next 2 -- scan() stops stepping once the view is invalid. */
      case "invalid":
        return;
      /* v8 ignore next 2 -- Every scanner mode has a handler above. */
      default:
        assertNever(this.#mode);
    }
  }
  fail() {
    this.#invalidAt = this.#consumed;
    this.#mode = "invalid";
    this.#current = null;
  }
  beginKey(at) {
    this.#mode = "key";
    this.#keyStart = at + 1;
    this.#keyEscaped = false;
    this.#escape = false;
  }
  stepKey(c, at) {
    if (c < " ") {
      this.fail();
      return;
    }
    if (this.#escape) {
      this.#escape = false;
      return;
    }
    if (c === "\\") {
      this.#escape = true;
      this.#keyEscaped = true;
      return;
    }
    if (c !== '"') return;
    const raw = this.slice(this.#keyStart, at);
    if (this.#keyEscaped) try {
      this.#key = JSON.parse(`"${raw}"`);
    } catch (_error) {
      this.fail();
      return;
    }
    else this.#key = raw;
    this.#mode = "colon";
  }
  open(entry) {
    if (!this.#entries.has(this.#key)) this.#order.push(this.#key);
    this.#entries.set(this.#key, entry);
    this.#current = entry;
  }
  beginValue(c, at) {
    if (isWhitespace(c)) return;
    if (c === '"') {
      this.open({
        kind: "string",
        start: at + 1,
        end: -1,
        needsDecoding: false,
        invalidAt: void 0,
        length: void 0,
        text: void 0,
        prefixes: void 0
      });
      this.#escape = false;
      this.#mode = "string";
      return;
    }
    if (c === "}" || c === "," || c === ":" || c === "]") {
      this.fail();
      return;
    }
    this.open({
      kind: "value",
      start: at,
      end: -1,
      parsed: void 0,
      invalid: false
    });
    if (c === "{" || c === "[") {
      this.#mode = "nested";
      this.#nestedEnds = [c === "{" ? "}" : "]"];
      this.#nestedInString = false;
      this.#escape = false;
      return;
    }
    this.#mode = "scalar";
  }
  stepScalar(c, at) {
    if (c !== "," && c !== "}" && !isWhitespace(c)) return;
    this.closeValue(at);
    this.#mode = c === "," ? "key-only" : c === "}" ? "closed" : "comma-or-end";
  }
  stepNested(c, at) {
    if (this.#nestedInString) {
      this.#nestedInString = false;
      return;
    }
    if (c === '"') {
      this.#nestedInString = true;
      return;
    }
    if (c === "{" || c === "[") {
      this.#nestedEnds.push(c === "{" ? "}" : "]");
      return;
    }
    if (c === "}" || c === "]") {
      if (this.#nestedEnds.pop() !== c) {
        this.fail();
        return;
      }
      if (this.#nestedEnds.length === 0) {
        this.closeValue(at + 1);
        this.#mode = "comma-or-end";
      }
    }
  }
  closeValue(end) {
    const entry = this.#current;
    entry.end = end;
    this.#current = null;
  }
};
function assertNever(value, context) {
  const rendered = JSON.stringify(value) ?? String(value);
  throw new Error(`unreachable variant${context ? ` in ${context}` : ""}: ${rendered}`);
}

// reference/packages/client/shortcuts/src/configuration.ts
var record = (value) => typeof value === "object" && value !== null && !Array.isArray(value);
var commandPattern = /^[a-z][a-zA-Z0-9-]*(?:\.[a-zA-Z][a-zA-Z0-9-]*)+$/u;
function parseBinding(value) {
  if (value === null) return null;
  if (!record(value) || Object.keys(value).some((key) => key !== "code" && key !== "secondCode" && key !== "modifiers") || typeof value.code !== "string" || !Array.isArray(value.modifiers) || Object.hasOwn(value, "secondCode") && typeof value.secondCode !== "string" || !value.modifiers.every((modifier) => typeof modifier === "string" && ["primary", "control", "alt", "shift", "meta"].includes(modifier))) {
    throw new Error("Invalid shortcut binding");
  }
  const binding = {
    code: value.code,
    modifiers: value.modifiers,
    ...typeof value.secondCode === "string" ? { secondCode: value.secondCode } : {}
  };
  normalizeBinding(binding, "windows");
  return binding;
}
function parseShortcutDocument(raw) {
  if (raw === null) return { schemaVersion: 1, profiles: {} };
  try {
    const value = JSON.parse(raw);
    if (!record(value)) return "invalid";
    if (typeof value.schemaVersion === "number" && value.schemaVersion > 2) return "future";
    if (value.schemaVersion !== 1 && value.schemaVersion !== 2 || !record(value.profiles) || Object.keys(value).some((key) => key !== "schemaVersion" && key !== "profiles")) return "invalid";
    const profiles = {};
    for (const [profile, overrides] of Object.entries(value.profiles)) {
      if (!/^(desktop|web):(macos|windows|linux)$/u.test(profile) || !record(overrides)) return "invalid";
      const bindings = {};
      for (const [id, binding] of Object.entries(overrides)) {
        if (!commandPattern.test(id)) return "invalid";
        const parsed = parseBinding(binding);
        if (value.schemaVersion === 1 && parsed?.secondCode !== void 0) return "invalid";
        bindings[id] = parsed;
      }
      profiles[profile] = bindings;
    }
    return { schemaVersion: value.schemaVersion, profiles };
  } catch (_error) {
    return "invalid";
  }
}
function bindingIssue(binding, runtime, platform) {
  const { code, modifiers } = binding;
  if (runtime === "desktop" && (platform === "windows" || platform === "macos")) return null;
  if (binding.secondCode !== void 0) return "unsupported-key";
  if (modifiers.length === 0 || modifiers.every((modifier) => modifier === "shift")) return "modifier-required";
  if ((platform === "windows" || platform === "macos") && modifiers.length >= 3) return null;
  if (runtime === "web" && (platform === "windows" || platform === "macos") && isWebBindingAllowed(binding, platform)) return null;
  const primary = modifiers.includes(platform === "macos" ? "meta" : "control");
  if (["Escape", "Tab", "Space", "Backspace", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(code) || code === "Enter" && !modifiers.includes("alt") || primary && ["KeyC", "KeyV", "KeyX", "KeyZ", "KeyY", "KeyQ", "KeyH"].includes(code) || primary && code === "KeyA" && !modifiers.includes("shift") || platform !== "macos" && (modifiers.includes("meta") || modifiers.includes("alt") && ["F4", "F2"].includes(code)) || platform === "macos" && modifiers.includes("control") && modifiers.includes("meta") || platform === "macos" && modifiers.includes("alt") && !primary) return "reserved";
  if (runtime === "web" && !isWebBindingAllowed(binding, platform)) return "unsupported-browser";
  return null;
}
function resolveShortcutDefault(definition, runtime, platform) {
  return definition.defaults[`${runtime}:${platform}`];
}
function effectiveShortcuts(definitions, document, runtime, platform) {
  const overrides = document.profiles[`${runtime}:${platform}`] ?? {};
  const fixed = definitions.flatMap((row) => row.fixed?.map((binding) => ({ id: row.id, binding: normalizeBinding(binding, platform) })) ?? []);
  const rows = definitions.filter((row) => row.fixed === void 0).map(({ id, defaults }) => {
    const modified = Object.hasOwn(overrides, id);
    const candidate = modified ? overrides[id] : resolveShortcutDefault({ id, defaults }, runtime, platform);
    const binding = candidate == null ? null : normalizeBinding(candidate, platform);
    return { id, binding, modified, issue: binding === null ? null : bindingIssue(binding, runtime, platform) };
  });
  return rows.map((row) => {
    const binding = row.binding;
    return { ...row, conflicts: binding === null ? [] : [.../* @__PURE__ */ new Set([
      ...rows.filter((other) => other.id !== row.id && other.binding !== null && other.issue === null && overlappingBindings(other.binding, binding) && (!row.modified || other.modified)).map((other) => other.id),
      ...fixed.filter((other) => overlappingBindings(other.binding, binding)).map((other) => other.id)
    ])] };
  });
}
function overlappingBindings(left, right) {
  if (left.modifiers.join("+") !== right.modifiers.join("+")) return false;
  if (left.secondCode !== void 0 && right.secondCode !== void 0) return bindingKey(left) === bindingKey(right);
  return [left.code, left.secondCode].some((code) => code !== void 0 && (code === right.code || code === right.secondCode));
}
function editShortcutDocument(document, edit, runtime, platform) {
  const schemaVersion = runtime === "desktop" && (platform === "macos" || platform === "windows") ? 2 : document.schemaVersion;
  const profile = `${runtime}:${platform}`;
  let overrides = { ...document.profiles[profile] };
  switch (edit.type) {
    case "set":
      overrides[edit.id] = edit.binding;
      break;
    case "reset": {
      const { [edit.id]: _removed, ...remaining } = overrides;
      overrides = remaining;
      break;
    }
    case "reset-all":
      overrides = {};
      break;
    /* v8 ignore next -- parseShortcutEdit validates this closed union before persistence. */
    default:
      return assertNever(edit, "shortcut edit");
  }
  return { schemaVersion, profiles: { ...document.profiles, [profile]: overrides } };
}
function parseShortcutEdit(value) {
  if (!record(value)) throw new Error("Invalid shortcut edit");
  if (value.type === "reset-all" && Object.keys(value).length === 1) return { type: value.type };
  if (typeof value.id !== "string" || !commandPattern.test(value.id)) throw new Error("Invalid shortcut command");
  if (value.type === "reset" && Object.keys(value).length === 2) return { type: "reset", id: value.id };
  if (value.type === "set" && Object.keys(value).length === 3) return { type: "set", id: value.id, binding: parseBinding(value.binding) };
  throw new Error("Invalid shortcut edit");
}
function parseShortcutDefinitions(value) {
  if (!Array.isArray(value)) throw new Error("Invalid shortcut catalog");
  const ids = /* @__PURE__ */ new Set();
  for (const entry of value) {
    if (!record(entry) || typeof entry.id !== "string" || !commandPattern.test(entry.id) || ids.has(entry.id) || !record(entry.defaults) || Object.keys(entry).some((key) => key !== "id" && key !== "defaults" && key !== "fixed")) throw new Error("Invalid shortcut definition");
    ids.add(entry.id);
    if (Object.hasOwn(entry, "fixed")) {
      if (!Array.isArray(entry.fixed) || entry.fixed.length === 0 || Object.keys(entry.defaults).length > 0) throw new Error("Invalid fixed shortcut definition");
      for (const binding of entry.fixed) if (parseBinding(binding) === null) throw new Error("Invalid fixed shortcut binding");
    }
    for (const [profile, candidate] of Object.entries(entry.defaults)) {
      if (!/^(desktop|web):(macos|windows|linux)$/u.test(profile)) throw new Error("Invalid shortcut profile");
      const binding = parseBinding(candidate);
      if (binding === null) throw new Error("Invalid shortcut default");
    }
  }
  const definitions = value;
  for (const runtime of ["desktop", "web"]) {
    for (const platform of ["macos", "windows", "linux"]) {
      const bindings = [];
      for (const entry of definitions) {
        const binding = resolveShortcutDefault(entry, runtime, platform);
        if (binding === void 0) continue;
        const normalized = normalizeBinding(binding, platform);
        if (bindings.some((other) => overlappingBindings(other, normalized)) || bindingIssue(normalized, runtime, platform) !== null) throw new Error("Conflicting or reserved shortcut default");
        bindings.push(normalized);
      }
    }
  }
  return definitions;
}

// reference/packages/client/shortcuts/src/persistence.ts
var import_dsh_util_crypto = require("node:crypto");
function initialShortcutConfig() {
  return {
    revision: (0, import_dsh_util_crypto.randomUUID)(),
    sequence: 0,
    document: { schemaVersion: 1, profiles: {} },
    status: "loading",
    error: null,
    usingDefaults: true
  };
}
var ShortcutPersistence = class {
  constructor(storage, runtime, platform, rereadBeforeWrite, publish) {
    this.storage = storage;
    this.runtime = runtime;
    this.platform = platform;
    this.rereadBeforeWrite = rereadBeforeWrite;
    this.publish = publish;
  }
  snapshot = initialShortcutConfig();
  raw;
  queue = Promise.resolve();
  definitions = null;
  active = true;
  /**
   * Install or revoke a product catalog and invalidate drafts from its previous lifetime.
   * @param definitions - current trusted definitions, or null while the product is not ready.
   */
  setDefinitions(definitions) {
    this.definitions = definitions;
    this.accept({ ...this.snapshot });
  }
  /** Stop accepting edits or publishing late completions. */
  dispose() {
    this.active = false;
  }
  /**
   * Read the current file; failures retain the last accepted document and disable ordinary writes.
   * @returns the accepted snapshot or diagnostic snapshot.
   */
  readCurrent() {
    return this.serialize(() => this.read());
  }
  /**
   * Compare the draft revision, validate the complete candidate, then persist before publishing.
   * @param edit - constrained preference operation.
   * @param revision - state against which the user reviewed the edit.
   * @returns a classified outcome and the currently accepted snapshot.
   */
  edit(edit, revision) {
    return this.serialize(async () => {
      if (this.rereadBeforeWrite) await this.read();
      const result = (status) => ({ status, snapshot: this.snapshot });
      if (!this.active || this.definitions === null || this.snapshot.status === "loading") return result("not-ready");
      if (revision !== this.snapshot.revision) return result("stale");
      if (this.snapshot.status === "unreadable") return result("unreadable");
      if ((edit.type === "set" || edit.type === "reset") && !this.definitions.some((row) => row.id === edit.id && row.fixed === void 0)) return result("not-ready");
      const document = editShortcutDocument(this.snapshot.document, edit, this.runtime, this.platform);
      const rows = effectiveShortcuts(this.definitions, document, this.runtime, this.platform);
      const invalid = rows.find((row) => (edit.type === "reset-all" || row.id === edit.id) && (row.issue !== null || row.conflicts.length > 0));
      const displaced = edit.type === "set" ? rows.find((row) => row.conflicts.includes(edit.id)) : void 0;
      if (invalid !== void 0 || displaced !== void 0) return {
        ...result("conflict"),
        ...invalid?.issue ? { issue: invalid.issue } : {},
        conflicts: invalid?.conflicts.length ? invalid.conflicts : displaced === void 0 ? [] : [displaced.id]
      };
      try {
        const raw = `${JSON.stringify(document, null, 2)}
`;
        await this.storage.write(raw);
        this.raw = raw;
        this.accept({ ...this.snapshot, document, status: "ready", error: null, usingDefaults: false });
        return result("saved");
      } catch (_error) {
        return result("write-failed");
      }
    });
  }
  serialize(operation) {
    const next = this.queue.then(operation);
    this.queue = next.catch(() => void 0);
    return next;
  }
  accept(snapshot) {
    this.snapshot = { ...snapshot, sequence: this.snapshot.sequence + 1, revision: (0, import_dsh_util_crypto.randomUUID)() };
    if (!this.active) return;
    try {
      this.publish(this.snapshot);
    } catch (error) {
      console.error("Shortcut configuration subscriber failed:", error);
    }
  }
  async read() {
    let raw;
    try {
      raw = await this.storage.read();
    } catch (_error) {
      if (this.snapshot.error !== "read") this.accept({ ...this.snapshot, status: "unreadable", error: "read" });
      return this.snapshot;
    }
    if (raw === this.raw && this.snapshot.error !== "read") return this.snapshot;
    this.raw = raw;
    const document = parseShortcutDocument(raw);
    if (typeof document === "string") this.accept({ ...this.snapshot, status: "unreadable", error: document });
    else this.accept({ ...this.snapshot, document, status: "ready", error: null, usingDefaults: raw === null });
    return this.snapshot;
  }
};

// reference/apps/desktop/src/keybindings.ts
var import_promises2 = require("node:fs/promises");
var import_node_path2 = require("node:path");

// reference/packages/util/atomic-write/src/index.ts
var import_node_crypto = require("node:crypto");
var import_promises = require("node:fs/promises");
var import_node_path = require("node:path");
var WINDOWS_TRANSIENT_RENAME_ERRORS = /* @__PURE__ */ new Set(["EACCES", "EBUSY", "EPERM"]);
var WINDOWS_RENAME_RETRY_INITIAL_MS = 20;
var WINDOWS_RENAME_RETRY_MAX_MS = 200;
var WINDOWS_RENAME_RETRY_LIMIT = 8;
function isTransientWindowsRenameError(error) {
  if (process.platform !== "win32") return false;
  return WINDOWS_TRANSIENT_RENAME_ERRORS.has(error?.code ?? "");
}
async function renameAtomicTemp(temp, filename) {
  let delay = WINDOWS_RENAME_RETRY_INITIAL_MS;
  for (let retries = 0; ; retries += 1) {
    try {
      await (0, import_promises.rename)(temp, filename);
      return;
    } catch (error) {
      if (!isTransientWindowsRenameError(error)) throw error;
      if (retries >= WINDOWS_RENAME_RETRY_LIMIT) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(delay * 2, WINDOWS_RENAME_RETRY_MAX_MS);
  }
}
async function writeFileAtomic(filename, content, options) {
  await (0, import_promises.mkdir)((0, import_node_path.dirname)(filename), {
    recursive: true,
    ...options.dirMode === void 0 ? {} : { mode: options.dirMode }
  });
  const temp = `${filename}.${(0, import_node_crypto.randomBytes)(6).toString("hex")}.tmp`;
  try {
    await (0, import_promises.writeFile)(temp, content, { mode: options.mode, flag: "wx" });
    await renameAtomicTemp(temp, filename);
  } catch (error) {
    await (0, import_promises.rm)(temp, { force: true });
    throw error;
  }
}

// reference/apps/desktop/src/keybindings.ts
function desktopKeybindings(userData, platform, publish) {
  const path = (0, import_node_path2.join)(userData, "keybindings.json");
  return new ShortcutPersistence({
    read: async () => {
      try {
        return await (0, import_promises2.readFile)(path, "utf8");
      } catch (error) {
        if (error.code === "ENOENT") return null;
        throw error;
      }
    },
    write: (raw) => writeFileAtomic(path, raw, { mode: 384, dirMode: 448 })
  }, "desktop", platform, false, publish);
}

// reference/apps/desktop/src/ipc.ts
var DESKTOP_IPC = {
  fileSave: "dsh-desktop:file-save",
  clipboardImageRead: "dsh-desktop:clipboard-image-read",
  shortcutsInput: "dsh-desktop:shortcuts-input",
  shortcutsCloseWindow: "dsh-desktop:shortcuts-close-window",
  shortcutsGet: "dsh-desktop:shortcuts-get",
  shortcutsEdit: "dsh-desktop:shortcuts-edit",
  shortcutsChanged: "dsh-desktop:shortcuts-changed",
  shortcutsRecording: "dsh-desktop:shortcuts-recording",
  boot: "dsh-desktop:boot",
  enterWorkspace: "dsh-desktop:enter-workspace",
  onboardingActive: "dsh-desktop:onboarding-active",
  onboardingApiKey: "dsh-desktop:onboarding-api-key",
  bootFailed: "dsh-desktop:boot-failed",
  browserAcquire: "dsh-desktop:browser-acquire",
  browserRelease: "dsh-desktop:browser-release",
  browserOpenRequested: "dsh-desktop:browser-open-requested",
  directoryPick: "dsh-desktop:directory-pick",
  fileDragPrepare: "dsh-desktop:file-drag-prepare",
  fileDragCancel: "dsh-desktop:file-drag-cancel",
  fileDragStart: "dsh-desktop:file-drag-start",
  fileDragRelease: "dsh-desktop:file-drag-release",
  deviceInfo: "dsh-desktop:device-info",
  localeBootstrap: "dsh-desktop:locale-bootstrap",
  localeChanged: "dsh-desktop:locale-changed",
  updatesChannelGet: "dsh-desktop:updates-channel-get",
  updatesChannelSet: "dsh-desktop:updates-channel-set",
  updatesChannelChanged: "dsh-desktop:updates-channel-changed",
  updatesStatus: "dsh-desktop:updates-status",
  updatesOpen: "dsh-desktop:updates-open",
  updatesPresentation: "dsh-desktop:updates-presentation",
  nativeThemeSet: "dsh-desktop:native-theme-set",
  windowFullscreen: "dsh-desktop:window-fullscreen",
  windowsAppearance: "dsh-desktop:windows-appearance",
  windowsMenu: "dsh-desktop:windows-menu"
};
var SCHEME = "dsh-app";
function assertDesktopSender(event, hostnames) {
  const senderFrame = event.senderFrame;
  if (senderFrame === null) throw new Error("dsh desktop: rejected IPC without a sender frame");
  const url = new URL(senderFrame.url);
  if (url.protocol !== `${SCHEME}:` || !hostnames.includes(url.hostname)) {
    throw new Error("dsh desktop: rejected IPC from an unowned renderer");
  }
}

// reference/apps/desktop/src/keyboard.ts
function installDesktopShortcuts(getWindow, userData, platform, updateMenu, overlayInput) {
  let definitions = [];
  let recording = false;
  let revision;
  let closeBinding = null;
  let editingInput;
  const scopedDesktop = platform === "windows" || platform === "macos";
  const disposers = /* @__PURE__ */ new Set();
  const guestInputs = /* @__PURE__ */ new Map();
  const closeAccelerator = () => presentBinding(closeBinding, platform).aria?.replace("Meta+", "Command+").replace(/Arrow(Up|Down|Left|Right)$/u, "$1");
  const sendMenuClose = () => {
    const window = getWindow();
    if (window === void 0 || window.isDestroyed() || !window.isFocused() || !window.isEnabled() || revision === void 0 || recording || overlayInput(window).blocked) return;
    window.webContents.send(DESKTOP_IPC.shortcutsInput, { kind: "menu", commandId: "page.close", revision });
  };
  let keys = /* @__PURE__ */ new Set();
  const publish = (snapshot) => {
    const wasEnabled = revision !== void 0;
    const previousAccelerator = closeAccelerator();
    revision = definitions.length === 0 || snapshot.status === "loading" ? void 0 : snapshot.revision;
    const rows = snapshot.status === "loading" ? [] : effectiveShortcuts(definitions, snapshot.document, "desktop", platform);
    keys = new Set(rows.flatMap((row) => row.binding !== null && row.issue === null && row.conflicts.length === 0 ? [bindingKey(row.binding)] : []));
    const close = rows.find((row) => row.id === "page.close");
    closeBinding = close?.issue === null && close.conflicts.length === 0 ? close.binding : null;
    if (wasEnabled !== (revision !== void 0) || previousAccelerator !== closeAccelerator()) updateMenu();
    const window = getWindow();
    if (window !== void 0 && !window.isDestroyed() && window.webContents.mainFrame.url.startsWith("dsh-app://app/")) {
      window.webContents.send(DESKTOP_IPC.shortcutsChanged, snapshot);
    }
  };
  const persistence = desktopKeybindings(userData, platform, publish);
  const assertSender = (event) => {
    const window = getWindow();
    if (window === void 0 || window.isDestroyed() || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) throw new Error("desktop shortcuts: rejected sender");
    assertDesktopSender(event, ["app"]);
    return window;
  };
  import_electron.ipcMain.handle(DESKTOP_IPC.shortcutsGet, async (event, input) => {
    assertSender(event);
    definitions = parseShortcutDefinitions(input);
    persistence.setDefinitions(definitions);
    return persistence.readCurrent();
  });
  import_electron.ipcMain.handle(DESKTOP_IPC.shortcutsEdit, async (event, input, expectedRevision) => {
    assertSender(event);
    if (typeof expectedRevision !== "string") throw new Error("desktop shortcuts: invalid revision");
    return persistence.edit(parseShortcutEdit(input), expectedRevision);
  });
  import_electron.ipcMain.handle(DESKTOP_IPC.shortcutsRecording, (event, active) => {
    const window = assertSender(event);
    if (typeof active !== "boolean") throw new Error("desktop shortcuts: invalid recording state");
    recording = active;
    window.webContents.setIgnoreMenuShortcuts(active);
  });
  import_electron.ipcMain.handle(DESKTOP_IPC.shortcutsCloseWindow, (event, expected) => {
    const window = assertSender(event);
    if (expected !== revision || revision === void 0 || recording || !window.isFocused() || !window.isEnabled() || overlayInput(window).blocked) return;
    window.close();
  });
  function attachInput(window, contents, guestName) {
    let deadKey = false;
    const held = /* @__PURE__ */ new Set();
    const consumed = /* @__PURE__ */ new Map();
    let inputFrame = null;
    let inputRevision;
    let overlayRevision = overlayInput(window).revision;
    const resetInput = () => {
      deadKey = false;
      held.clear();
      consumed.clear();
      inputFrame = null;
      inputRevision = void 0;
      if (!contents.isDestroyed()) contents.setIgnoreMenuShortcuts(false);
    };
    if (guestName !== void 0) guestInputs.set(contents, { window, reset: resetInput });
    const resetWindow = () => {
      resetInput();
      for (const guest of guestInputs.values()) if (guest.window === window) guest.reset();
    };
    const clear = () => {
      resetInput();
      if (guestName !== void 0) return;
      definitions = [];
      keys.clear();
      recording = false;
      persistence.setDefinitions(null);
    };
    const navigation = (_event, _url, inPlace, isMainFrame) => {
      if (isMainFrame && !inPlace) clear();
    };
    const beforeInput = (event, input) => {
      const overlay = overlayInput(window);
      if (overlay.revision !== overlayRevision) {
        resetInput();
        overlayRevision = overlay.revision;
      }
      if (overlay.blocked) {
        event.preventDefault();
        return;
      }
      if (event.defaultPrevented) {
        resetInput();
        return;
      }
      if (editingInput === contents) {
        held.clear();
        consumed.clear();
        contents.setIgnoreMenuShortcuts(true);
        return;
      }
      if (window !== getWindow() || !window.isFocused() || !window.isEnabled() || revision === void 0 || guestName !== void 0 && !contents.isFocused()) {
        contents.setIgnoreMenuShortcuts(false);
        held.clear();
        consumed.clear();
        return;
      }
      const modifiers = ["control", "alt", "shift", "meta"].filter((modifier) => input[modifier]);
      const key = bindingKey({ code: input.code, modifiers });
      const match = keys.has(key);
      const menuMatch = closeBinding !== null && closeBinding.secondCode === void 0 && modifiers.join("+") === closeBinding.modifiers.join("+") && input.key.toUpperCase() === (closeBinding.code.startsWith("Key") ? closeBinding.code.slice(3) : input.code === closeBinding.code ? input.key.toUpperCase() : "");
      contents.setIgnoreMenuShortcuts(recording || match || menuMatch);
      const frame = contents.focusedFrame ?? contents.mainFrame;
      const composing = input.isComposing || input.key === "Dead" || deadKey || input.modifiers.includes("altgr");
      if (input.type === "keyDown") deadKey = input.key === "Dead";
      if (recording || composing || frame === null) {
        held.clear();
        consumed.clear();
        return;
      }
      let binding = { code: input.code, modifiers };
      let priority = false;
      if (scopedDesktop) {
        if (frame !== inputFrame || inputRevision !== revision) {
          held.clear();
          inputFrame = frame;
          inputRevision = revision;
        }
        const modifierKey = /^(Control|Alt|Shift|Meta)(Left|Right)$/u.test(input.code);
        if (input.type === "keyUp") {
          if (consumed.get(input.code) === "press") event.preventDefault();
          consumed.delete(input.code);
          held.delete(input.code);
          if (modifierKey) held.clear();
          return;
        }
        if (!input.isAutoRepeat) consumed.delete(input.code);
        if (modifierKey) {
          held.clear();
          return;
        }
        if (input.isAutoRepeat && consumed.has(input.code) && !match) {
          event.preventDefault();
          return;
        }
        if (input.isAutoRepeat && !held.has(input.code) && !match) return;
        held.add(input.code);
        const codes = [input.code, ...[...held].filter((value) => value !== input.code)];
        codes.sort();
        const pair = { code: codes[0], ...codes[1] === void 0 ? {} : { secondCode: codes[1] }, modifiers };
        priority = keys.has(key);
        if (codes.length === 2 && keys.has(bindingKey(pair))) {
          binding = pair;
          priority = true;
        }
      }
      const main = guestName === void 0 && frame === contents.mainFrame;
      if (!priority && (main || !match)) return;
      event.preventDefault();
      if (input.type !== "keyDown") return;
      if (scopedDesktop) {
        if (!input.isAutoRepeat) {
          if (binding.secondCode !== void 0) {
            consumed.set(binding.code, "repeat");
            consumed.set(binding.secondCode, "repeat");
          }
          consumed.set(input.code, "press");
        }
        held.clear();
      }
      let embedding = frame;
      while (guestName === void 0 && !main && embedding.parent !== null && embedding.parent !== contents.mainFrame) {
        embedding = embedding.parent;
      }
      window.webContents.send(DESKTOP_IPC.shortcutsInput, {
        kind: guestName === void 0 ? main ? "keyboard" : "iframe" : "webview",
        revision,
        frameName: guestName ?? (main ? "" : embedding.name),
        code: binding.code,
        ...binding.secondCode === void 0 ? {} : { secondCode: binding.secondCode },
        repeat: input.isAutoRepeat,
        control: input.control,
        alt: input.alt,
        shift: input.shift,
        meta: input.meta
      });
    };
    const dispose = () => {
      contents.off("did-start-navigation", navigation);
      contents.off("before-input-event", beforeInput);
      contents.off("blur", resetInput);
      contents.off("destroyed", dispose);
      if (guestName === void 0) {
        window.off("blur", resetWindow);
        window.off("closed", closed);
      }
      disposers.delete(dispose);
      guestInputs.delete(contents);
      if (!contents.isDestroyed()) contents.setIgnoreMenuShortcuts(false);
    };
    const closed = () => {
      clear();
      dispose();
    };
    contents.on("did-start-navigation", navigation);
    contents.on("before-input-event", beforeInput);
    contents.on("blur", resetInput);
    contents.once("destroyed", dispose);
    if (guestName === void 0) {
      window.on("closed", closed);
      window.on("blur", resetWindow);
    }
    disposers.add(dispose);
    return dispose;
  }
  return {
    sendEditingKey(keyCode, modifiers) {
      const window = getWindow();
      if (window === void 0 || window.isDestroyed() || overlayInput(window).blocked) return;
      const contents = [...guestInputs].find(([guest, owner]) => owner.window === window && !guest.isDestroyed() && guest.isFocused())?.[0] ?? window.webContents;
      contents.focus();
      const previous = editingInput;
      editingInput = contents;
      try {
        contents.sendInputEvent({ type: "keyDown", keyCode, modifiers });
        contents.sendInputEvent({ type: "keyUp", keyCode, modifiers });
      } finally {
        editingInput = previous;
        if (!contents.isDestroyed()) contents.setIgnoreMenuShortcuts(recording);
      }
    },
    fileMenu: (labels) => {
      const accelerator = closeAccelerator();
      return { label: labels.fileMenu, submenu: [{
        id: "dsh-page-close",
        label: labels.closePage,
        enabled: revision !== void 0,
        ...accelerator === void 0 ? {} : { accelerator },
        click: sendMenuClose
      }] };
    },
    attach(window) {
      attachInput(window, window.webContents);
    },
    attachGuest: attachInput,
    dispose() {
      for (const dispose of disposers) dispose();
      persistence.dispose();
      for (const channel of [
        DESKTOP_IPC.shortcutsGet,
        DESKTOP_IPC.shortcutsEdit,
        DESKTOP_IPC.shortcutsRecording,
        DESKTOP_IPC.shortcutsCloseWindow
      ]) {
        import_electron.ipcMain.removeHandler(channel);
      }
    }
  };
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  installDesktopShortcuts
});
