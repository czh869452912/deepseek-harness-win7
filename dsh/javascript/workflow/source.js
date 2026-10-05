"use strict";
var __workflowSource = (() => {
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

  // scripts/native/workflow/entry.ts
  var entry_exports = {};
  __export(entry_exports, {
    runWorkerSession: () => runWorkerSession
  });

  // reference/packages/llm/llm/src/error.ts
  var HarnessError = class extends Error {
    /** Stable machine-routable failure class (e.g. `RATE_LIMIT`); route on this, never by parsing `message`. */
    code;
    constructor(message, code, options) {
      super(message, options);
      this.code = code;
      this.name = new.target.name;
    }
  };
  var STRUCTURED_CONTEXT_OVERFLOW = new RegExp(
    String.raw`(?:^|[^a-z0-9])context[\s_-](?:length|window)[\s_-]` + String.raw`(?:exceed(?:ed|s)?|overflow(?:ed)?|limit[\s_-]exceeded)(?:$|[^a-z0-9])`,
    "i"
  );
  var TOO_LARGE_FOR_CONTEXT = new RegExp(
    String.raw`\b(?:request|prompt|input|messages?)\s+(?:is\s+|are\s+)?` + String.raw`too\s+(?:large|long)\s+for\s+(?:(?:this|the)\s+)?` + String.raw`(?:model(?:'s)?\s+)?context(?:\s+window)?\b`,
    "i"
  );
  var EXCEEDS_MODEL_CONTEXT = new RegExp(
    String.raw`\b(?:input|prompt|request|messages?)\b.{0,40}` + String.raw`\b(?:exceed(?:s|ed)?|overflows?|is\s+larger\s+than)\b.{0,40}` + String.raw`\b(?:the\s+)?(?:model(?:'s)?\s+)?context(?:\s+(?:length|window))?\b`,
    "i"
  );

  // reference/packages/llm/llm/src/never.ts
  function assertNever(value, context) {
    const rendered = JSON.stringify(value) ?? String(value);
    throw new Error(`unreachable variant${context ? ` in ${context}` : ""}: ${rendered}`);
  }

  // reference/packages/workflow/workflow-worker-thread/src/realm.ts
  var MaterializeError = class extends Error {
    constructor(path, reason) {
      super(`${path}: ${reason}`);
      this.path = path;
      this.reason = reason;
      this.name = "MaterializeError";
    }
    path;
    reason;
  };
  function renderThrown(error) {
    try {
      const stack = error?.stack;
      if (typeof stack === "string" && stack.length > 0) return stack;
      const message = error?.message;
      if (typeof message === "string" && message.length > 0) return message;
      return String(error);
    } catch {
      return "[unrenderable thrown value]";
    }
  }
  function hasPlainPrototype(value) {
    const proto = Object.getPrototypeOf(value);
    if (proto === null) return true;
    return Object.getPrototypeOf(proto) === null;
  }
  function materializeFromRealm(value, root = "value") {
    if (value === void 0) return void 0;
    try {
      return materialize(value, root, /* @__PURE__ */ new Set());
    } catch (error) {
      if (error instanceof MaterializeError) throw error;
      throw new MaterializeError(root, `reading the value threw: ${renderThrown(error)}`);
    }
  }
  function materialize(value, path, seen) {
    switch (typeof value) {
      case "boolean":
      case "string":
        return value;
      case "number": {
        if (!Number.isFinite(value)) throw new MaterializeError(path, "non-finite numbers are not JSON data");
        return value;
      }
      case "bigint":
        throw new MaterializeError(path, "bigints are not JSON data");
      case "function":
        throw new MaterializeError(path, "functions are not plain JSON data");
      case "symbol":
        throw new MaterializeError(path, "symbols are not plain JSON data");
      case "undefined":
        throw new MaterializeError(path, "undefined is not JSON data");
      case "object":
        break;
    }
    if (value === null) return null;
    const objectValue = value;
    if (seen.has(objectValue)) throw new MaterializeError(path, "circular references are not JSON data");
    seen.add(objectValue);
    try {
      if (Array.isArray(objectValue)) return materializeArray(objectValue, path, seen);
      return materializeObject(objectValue, path, seen);
    } finally {
      seen.delete(objectValue);
    }
  }
  function materializeArray(value, path, seen) {
    const out = [];
    for (let index = 0; index < value.length; index++) {
      if (!(index in value)) throw new MaterializeError(`${path}[${index}]`, "sparse arrays are not JSON data");
      out.push(materialize(value[index], `${path}[${index}]`, seen));
    }
    for (const key of Object.keys(value)) {
      const index = Number(key);
      if (!Number.isInteger(index) || index < 0 || index >= value.length) {
        throw new MaterializeError(`${path}.${key}`, "arrays with non-index properties are not JSON data");
      }
    }
    if (Object.getOwnPropertySymbols(value).length > 0) {
      throw new MaterializeError(path, "symbol-keyed properties are not plain JSON data");
    }
    return out;
  }
  function materializeObject(value, path, seen) {
    if (!hasPlainPrototype(value)) {
      throw new MaterializeError(path, "only plain objects and arrays are JSON data (exotic prototype)");
    }
    if (Object.getOwnPropertySymbols(value).length > 0) {
      throw new MaterializeError(path, "symbol-keyed properties are not plain JSON data");
    }
    const out = {};
    for (const key of Object.keys(value)) {
      Object.defineProperty(out, key, {
        value: materialize(value[key], `${path}.${key}`, seen),
        enumerable: true,
        writable: true,
        configurable: true
      });
    }
    return out;
  }

  // scripts/native/workflow/vm.js
  var Script = class {
    constructor(source, options) {
      if (source !== "(async () => {\n" + globalThis.__request.body + "\n})()") {
        throw new Error("owned workflow wrapper differs");
      }
      this.options = options;
    }
    runInContext(context, options) {
      return globalThis.__runCompiled(context, options);
    }
  };
  function createContext(values, options) {
    return values;
  }

  // reference/packages/core/session/src/types.ts
  function SessionId(id) {
    return id;
  }

  // reference/packages/core/session/src/json.ts
  function hasIntrinsicConstructor(prototype, name) {
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "constructor");
    const constructor = descriptor?.value;
    if (typeof constructor !== "function") return false;
    try {
      return constructor.name === name && constructor.prototype === prototype && Function.prototype.toString.call(constructor) === `function ${name}() { [native code] }`;
    } catch {
      return false;
    }
  }
  function isIntrinsicObjectPrototype(value) {
    return Object.getPrototypeOf(value) === null && hasIntrinsicConstructor(value, "Object");
  }
  function hasPlainArrayPrototype(value) {
    const prototype = Object.getPrototypeOf(value);
    if (!Array.isArray(prototype) || !hasIntrinsicConstructor(prototype, "Array")) return false;
    const objectPrototype = Object.getPrototypeOf(prototype);
    return typeof objectPrototype === "object" && objectPrototype !== null && isIntrinsicObjectPrototype(objectPrototype);
  }
  function hasPlainObjectPrototype(value) {
    const prototype = Object.getPrototypeOf(value);
    return prototype === null || typeof prototype === "object" && isIntrinsicObjectPrototype(prototype);
  }
  function enumerableStringKeys(value) {
    const keys = Reflect.ownKeys(value);
    if (keys.some((key) => typeof key !== "string" || !Object.prototype.propertyIsEnumerable.call(value, key))) return void 0;
    return keys;
  }
  function walkJsonValue(value, detach) {
    const ancestors = /* @__PURE__ */ new Set();
    let root;
    const assign = (destination, item) => {
      if (destination === void 0) return;
      if (destination.kind === "root") {
        root = item;
      } else if (destination.kind === "array") {
        destination.target[destination.index] = item;
      } else {
        Object.defineProperty(destination.target, destination.key, {
          value: item,
          enumerable: true,
          configurable: true,
          writable: true
        });
      }
    };
    const tasks = [{
      kind: "visit",
      value,
      ...detach ? { destination: { kind: "root" } } : {}
    }];
    for (let task = tasks.pop(); task !== void 0; task = tasks.pop()) {
      if (task.kind === "leave") {
        ancestors.delete(task.source);
        continue;
      }
      if (task.kind === "array-item") {
        if (!Object.prototype.hasOwnProperty.call(task.source, task.index)) return void 0;
        tasks.push({
          kind: "visit",
          value: task.source[task.index],
          ...task.target === void 0 ? {} : { destination: { kind: "array", target: task.target, index: task.index } }
        });
        continue;
      }
      if (task.kind === "object-property") {
        tasks.push({
          kind: "visit",
          value: task.source[task.key],
          ...task.target === void 0 ? {} : { destination: { kind: "object", target: task.target, key: task.key } }
        });
        continue;
      }
      const current = task.value;
      if (current === null) {
        assign(task.destination, null);
        continue;
      }
      if (typeof current === "boolean" || typeof current === "string") {
        assign(task.destination, current);
        continue;
      }
      if (typeof current === "number") {
        if (!Number.isFinite(current) || Object.is(current, -0)) return void 0;
        assign(task.destination, current);
        continue;
      }
      if (typeof current !== "object") return void 0;
      if (ancestors.has(current)) return void 0;
      if (Array.isArray(current)) {
        if (!hasPlainArrayPrototype(current)) return void 0;
        const length = current.length;
        if (Reflect.ownKeys(current).length !== length + 1) return void 0;
        const target2 = detach ? [] : void 0;
        if (target2 !== void 0) assign(task.destination, target2);
        ancestors.add(current);
        tasks.push({ kind: "leave", source: current });
        for (let index = length - 1; index >= 0; index--) {
          tasks.push({ kind: "array-item", source: current, index, ...target2 === void 0 ? {} : { target: target2 } });
        }
        continue;
      }
      if (!hasPlainObjectPrototype(current)) return void 0;
      const keys = enumerableStringKeys(current);
      if (keys === void 0) return void 0;
      const target = detach ? {} : void 0;
      if (target !== void 0) assign(task.destination, target);
      ancestors.add(current);
      tasks.push({ kind: "leave", source: current });
      for (let index = keys.length - 1; index >= 0; index--) {
        const key = keys[index];
        if (key === void 0) return void 0;
        tasks.push({ kind: "object-property", source: current, key, ...target === void 0 ? {} : { target } });
      }
    }
    return detach ? root : true;
  }
  function isJsonValue(value) {
    return walkJsonValue(value, false) === true;
  }

  // reference/packages/core/tools/src/json-schema.ts
  var JsonSchemaError = class extends HarnessError {
    /** Individual schema violations in walk order. */
    violations;
    constructor(violations) {
      super(`unsupported JSON schema: ${violations.join("; ")}`, "UNSUPPORTED_SCHEMA");
      this.name = "JsonSchemaError";
      this.violations = violations;
    }
  };
  var CONSTRAINT_KEYWORDS = /* @__PURE__ */ new Set([
    "type",
    "oneOf",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const"
  ]);
  var ANNOTATION_KEYWORDS = /* @__PURE__ */ new Set(["description", "title", "default", "examples"]);
  var SCHEMA_TYPES = ["object", "array", "string", "number", "integer", "boolean", "null"];
  function hasIntrinsicConstructor2(prototype, name) {
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "constructor");
    const constructor = descriptor?.value;
    if (typeof constructor !== "function") return false;
    try {
      return constructor.name === name && constructor.prototype === prototype && Function.prototype.toString.call(constructor) === `function ${name}() { [native code] }`;
    } catch {
      return false;
    }
  }
  function isIntrinsicObjectPrototype2(value) {
    return Object.getPrototypeOf(value) === null && hasIntrinsicConstructor2(value, "Object");
  }
  function isPlainJsonRecord(value) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    try {
      const prototype = Object.getPrototypeOf(value);
      return prototype === null || typeof prototype === "object" && isIntrinsicObjectPrototype2(prototype);
    } catch {
      return false;
    }
  }
  function hasPlainArrayPrototype2(value) {
    const prototype = Object.getPrototypeOf(value);
    if (!Array.isArray(prototype) || !hasIntrinsicConstructor2(prototype, "Array")) return false;
    const objectPrototype = Object.getPrototypeOf(prototype);
    return typeof objectPrototype === "object" && objectPrototype !== null && isIntrinsicObjectPrototype2(objectPrototype);
  }
  function hasOnlyEnumerableStringKeys(value) {
    try {
      return Reflect.ownKeys(value).every((key) => typeof key === "string" && Object.prototype.propertyIsEnumerable.call(value, key));
    } catch {
      return false;
    }
  }
  function isJsonSchemaRecord(value) {
    return isPlainJsonRecord(value) && hasOnlyEnumerableStringKeys(value);
  }
  function isPlainJsonArray(value) {
    if (!Array.isArray(value)) return false;
    try {
      if (!hasPlainArrayPrototype2(value) || Reflect.ownKeys(value).length !== value.length + 1) return false;
      for (let index = 0; index < value.length; index++) {
        if (!Object.hasOwn(value, index)) return false;
      }
      return true;
    } catch {
      return false;
    }
  }
  function isJsonNumber(value) {
    return typeof value === "number" && Number.isFinite(value) && !Object.is(value, -0);
  }
  function scalarMatches(type, value) {
    switch (type) {
      case "string":
        return typeof value === "string";
      case "number":
        return isJsonNumber(value);
      case "integer":
        return isJsonNumber(value) && Number.isInteger(value);
      case "boolean":
        return typeof value === "boolean";
      case "null":
        return value === null;
      /* v8 ignore next -- JsonSchemaScalarType is closed; this retains compile-time exhaustiveness. */
      default:
        return assertNever(type, "JsonSchemaType");
    }
  }
  var ONE_OF_SIBLING_KEYWORDS = ["properties", "required", "additionalProperties", "items", "enum", "const"];
  function checkObjectSchemaTail(node, path, properties, violations) {
    const hasRequired = Object.hasOwn(node, "required");
    const required = hasRequired ? node.required : void 0;
    if (hasRequired) {
      if (!isPlainJsonArray(required) || required.some((entry) => typeof entry !== "string")) {
        violations.push(`${path}.required must be an array of strings`);
      } else {
        const declared = isJsonSchemaRecord(properties) ? properties : {};
        for (const key of required) {
          if (!Object.hasOwn(declared, key)) violations.push(`${path}.required names "${key}" which is not in properties`);
        }
      }
    }
    if (Object.hasOwn(node, "additionalProperties") && typeof node.additionalProperties !== "boolean") {
      violations.push(`${path}.additionalProperties must be a boolean`);
    }
  }
  function checkSchemaNode(root, rootPath, violations, seen) {
    const tasks = [{ kind: "enter", node: root, path: rootPath }];
    for (let task = tasks.pop(); task !== void 0; task = tasks.pop()) {
      if (task.kind === "leave") {
        seen.delete(task.node);
        continue;
      }
      if (task.kind === "one-of-tail") {
        for (const key of ONE_OF_SIBLING_KEYWORDS) {
          if (Object.hasOwn(task.node, key)) violations.push(`${task.path}.${key} is not supported beside oneOf`);
        }
        continue;
      }
      if (task.kind === "object-tail") {
        checkObjectSchemaTail(task.node, task.path, task.properties, violations);
        continue;
      }
      const { node, path } = task;
      if (!isJsonSchemaRecord(node)) {
        violations.push(`${path} must be a schema object`);
        continue;
      }
      if (seen.has(node)) {
        violations.push(`${path} is circular`);
        continue;
      }
      seen.add(node);
      tasks.push({ kind: "leave", node });
      for (const key of Object.keys(node)) {
        if (CONSTRAINT_KEYWORDS.has(key)) continue;
        if (ANNOTATION_KEYWORDS.has(key)) {
          try {
            if (!isJsonValue(node[key])) violations.push(`${path}.${key} annotation must be lossless JSON data`);
          } catch {
            violations.push(`${path}.${key} annotation must be lossless JSON data`);
          }
          continue;
        }
        violations.push(`${path}.${key} is not a supported keyword (subset: type/oneOf/properties/required/additionalProperties/items/enum/const + annotations)`);
      }
      if (Object.hasOwn(node, "description") && typeof node.description !== "string") {
        violations.push(`${path}.description must be a string`);
      }
      if (Object.hasOwn(node, "title") && typeof node.title !== "string") {
        violations.push(`${path}.title must be a string`);
      }
      const hasType = Object.hasOwn(node, "type");
      const hasOneOf = Object.hasOwn(node, "oneOf");
      if (hasType && hasOneOf) {
        violations.push(`${path} cannot declare both type and oneOf`);
        continue;
      }
      if (!hasType && !hasOneOf) {
        for (const key of ONE_OF_SIBLING_KEYWORDS) {
          if (Object.hasOwn(node, key)) violations.push(`${path}.${key} requires type or oneOf`);
        }
        continue;
      }
      if (hasOneOf) {
        const oneOf = node.oneOf;
        tasks.push({ kind: "one-of-tail", node, path });
        if (!isPlainJsonArray(oneOf) || oneOf.length < 2) {
          violations.push(`${path}.oneOf must be an array of at least two schemas`);
        } else {
          for (let index = oneOf.length - 1; index >= 0; index--) {
            tasks.push({ kind: "enter", node: oneOf[index], path: `${path}.oneOf[${index}]` });
          }
        }
        continue;
      }
      const type = node.type;
      if (typeof type !== "string" || !SCHEMA_TYPES.includes(type)) {
        violations.push(Array.isArray(type) ? `${path}.type must be a single type string (type arrays are not supported)` : `${path}.type must be one of ${SCHEMA_TYPES.join("/")}`);
        continue;
      }
      const schemaType = type;
      const allowedFor = {
        properties: ["object"],
        required: ["object"],
        additionalProperties: ["object"],
        items: ["array"],
        enum: ["string", "number", "integer", "boolean", "null"],
        const: ["string", "number", "integer", "boolean", "null"]
      };
      for (const [key, types] of Object.entries(allowedFor)) {
        if (Object.hasOwn(node, key) && !types.includes(schemaType)) {
          violations.push(`${path}.${key} is not supported on type "${schemaType}"`);
        }
      }
      switch (schemaType) {
        case "object": {
          const properties = Object.hasOwn(node, "properties") ? node.properties : void 0;
          tasks.push({ kind: "object-tail", node, path, properties });
          if (Object.hasOwn(node, "properties")) {
            if (!isJsonSchemaRecord(properties)) {
              violations.push(`${path}.properties must be an object of schemas`);
            } else {
              const entries = Object.entries(properties);
              for (let index = entries.length - 1; index >= 0; index--) {
                const entry = entries[index];
                if (entry === void 0) continue;
                tasks.push({ kind: "enter", node: entry[1], path: `${path}.properties.${entry[0]}` });
              }
            }
          }
          break;
        }
        case "array": {
          if (Object.hasOwn(node, "items")) tasks.push({ kind: "enter", node: node.items, path: `${path}.items` });
          break;
        }
        case "string":
        case "number":
        case "integer":
        case "boolean":
        case "null": {
          const hasEnum = Object.hasOwn(node, "enum");
          const allowed = hasEnum ? node.enum : void 0;
          const enumValid = isPlainJsonArray(allowed) && allowed.length > 0 && allowed.every((entry) => scalarMatches(schemaType, entry));
          if (hasEnum && !enumValid) {
            violations.push(`${path}.enum must be a non-empty array of ${schemaType} values`);
          }
          const hasConst = Object.hasOwn(node, "const");
          const declaredConst = hasConst ? node.const : void 0;
          const constValid = scalarMatches(schemaType, declaredConst);
          if (hasConst) {
            if (!constValid) {
              violations.push(`${path}.const must be a ${schemaType} value`);
            } else if (enumValid && !allowed.includes(declaredConst)) {
              violations.push(`${path}.const must be one of ${path}.enum when both are declared`);
            }
          }
          break;
        }
        /* v8 ignore next -- schemaType was narrowed from the closed SCHEMA_TYPES table above. */
        default:
          assertNever(schemaType, "JsonSchemaType");
      }
    }
  }
  function assertObjectJsonSchema(schema) {
    const violations = [];
    checkSchemaNode(schema, "schema", violations, /* @__PURE__ */ new Set());
    if (violations.length === 0 && (!isJsonSchemaRecord(schema) || !Object.hasOwn(schema, "type") || schema.type !== "object")) {
      violations.push('schema.type must be "object" (structured output is object-rooted)');
    }
    if (violations.length > 0) throw new JsonSchemaError(violations);
  }

  // reference/packages/workflow/workflow/src/index.ts
  var WorkflowError = class extends HarnessError {
    /** Whether combinators must propagate this error instead of nulling the item. */
    fatal;
    constructor(message, code, options) {
      super(message, code, options);
      this.name = "WorkflowError";
      this.fatal = options?.fatal ?? true;
    }
  };
  function isFatalWorkflowError(error) {
    return error instanceof WorkflowError && error.fatal;
  }

  // reference/packages/workflow/workflow-worker-thread/src/runtime.ts
  var SUPPORTED_AGENT_OPTIONS = /* @__PURE__ */ new Set(["label", "phase", "schema", "provider", "model"]);
  var DEFERRED_AGENT_OPTIONS = /* @__PURE__ */ new Set(["effort", "isolation", "agentType"]);
  function outputText(blocks) {
    return blocks.filter((block) => block.type === "text").map((block) => block.text).join("");
  }
  function defaultLabel(prompt) {
    const newline = prompt.indexOf("\n");
    const line = newline === -1 ? prompt : prompt.slice(0, newline);
    return line.length <= 48 ? line : `${line.slice(0, 47)}\u2026`;
  }
  var WorkflowExecution = class {
    constructor(meta, body, args, limits, observer, children) {
      this.limits = limits;
      this.observer = observer;
      this.children = children;
      try {
        this.compiled = new Script(`(async () => {
${body}
})()`, {
          filename: `workflow:${meta.name}`,
          lineOffset: -1
        });
      } catch (error) {
        throw new WorkflowError(`workflow script does not parse: ${String(error)}`, "SCRIPT_PARSE", { cause: error });
      }
      this.context = createContext({}, { name: `workflow:${meta.name}` });
      const globals = {
        agent: (prompt, opts) => this.contain(this.agent(prompt, opts)),
        parallel: (thunks) => this.contain(this.parallel(thunks)),
        pipeline: (items, ...stages) => this.contain(this.pipeline(items, stages)),
        phase: (title) => {
          this.phase(title);
        },
        log: (message) => {
          this.log(message);
        },
        // workerData already performed the real cross-thread structured clone.
        args
      };
      for (const [key, value] of Object.entries(globals)) {
        ;
        this.context[key] = typeof value === "function" ? Object.freeze(value) : value;
      }
    }
    limits;
    observer;
    children;
    /** 1-based count of `agent()` calls started (the `agentsStarted` result field). */
    started = 0;
    activeSlots = 0;
    slotWaiters = [];
    cancelReason;
    cancelError;
    currentPhase;
    context;
    compiled;
    /**
     * Whether the run has been cancelled. A METHOD, not an inline property
     * read: `cancel()` mutates `cancelReason` concurrently (the session's
     * message handler), and an inline read after an `await` gets narrowed by
     * control flow into an always-false comparison.
     */
    isCancelled() {
      return this.cancelReason !== void 0;
    }
    /**
     * Shared hook entry guard: after {@link cancel}, EVERY hook throws
     * `CANCELLED` at its next call — cancellation is the next HOOK boundary,
     * not just the next `agent()`, so a script that caught one cancelled
     * rejection cannot keep emitting progress through `phase`/`log` or enter a
     * combinator.
     */
    throwIfCancelled() {
      if (this.isCancelled()) throw this.cancelledError();
    }
    /**
     * Cancel the run: waiting `agent()` slots reject and every future hook call
     * throws `CANCELLED` — the script dies at its next await. A script that
     * never settles anyway (parked on a promise no hook owns) is the HOST's
     * problem: its grace timer force-settles the run and terminates the
     * worker. Idempotent; the first reason wins.
     * @param reason - human-readable cause carried on the CANCELLED error. The
     * host independently aborts the required signal shared by every child.
     */
    cancel(reason) {
      if (this.cancelReason !== void 0) return;
      this.cancelReason = reason;
      this.cancelError = new WorkflowError(`workflow run cancelled: ${this.cancelReason}`, "CANCELLED");
      for (const waiter of this.slotWaiters.splice(0)) waiter.reject(this.cancelledError());
    }
    /**
     * Run the script to settlement. Resolves — never rejects — with the run's
     * {@link WorkflowResult}: the materialized return value on `completed`, the
     * failure message on `error`, and `cancelled` when the script died of
     * cancellation. This method only chooses the result; the session publishes
     * it and the host owns terminal child cancellation.
     * @returns the settled outcome — this promise NEVER rejects (the seam's
     * `result`-never-rejects contract); every failure maps to a variant.
     */
    async drive() {
      try {
        if (this.isCancelled()) throw this.cancelledError();
        const scriptPromise = this.compiled.runInContext(this.context, { timeout: this.limits.syncTimeoutMs });
        const raw = await this.contain(Promise.resolve(scriptPromise));
        if (this.isCancelled()) throw this.cancelledError();
        const value = raw === void 0 ? null : this.materializeResult(raw);
        return { value, stopReason: "completed", agentsStarted: this.started };
      } catch (error) {
        if (this.isCancelled()) {
          return { value: null, stopReason: "cancelled", error: this.cancelledError().message, agentsStarted: this.started };
        }
        return { value: null, stopReason: "error", error: renderThrown(error), agentsStarted: this.started };
      }
    }
    /**
     * Attach a no-op rejection consumer WITHOUT changing what the caller
     * receives: if the script drops the promise (no await), cancellation cannot
     * become an unhandled rejection (which would kill the worker thread); if
     * the script does await it, it still observes the rejection.
     */
    contain(promise) {
      promise.catch(() => {
      });
      return promise;
    }
    cancelledError() {
      return this.cancelError ?? new WorkflowError("workflow run cancelled", "CANCELLED");
    }
    /** Materialize the script's return value; violations become RESULT_UNSERIALIZABLE. */
    materializeResult(raw) {
      try {
        return materializeFromRealm(raw, "workflow result");
      } catch (error) {
        if (!(error instanceof MaterializeError)) throw error;
        throw new WorkflowError(
          `the workflow's return value is not plain JSON data \u2014 ${error.message}. Return only JSON-serializable objects/arrays/scalars.`,
          "RESULT_UNSERIALIZABLE",
          { cause: error }
        );
      }
    }
    /**
     * Acquire one concurrency slot (FIFO). Cancellation rejects QUEUED waiters
     * (see {@link cancel}); the callers guard their own entry and post-acquire
     * windows, so no cancelled-precheck is duplicated here.
     */
    acquireSlot() {
      if (this.activeSlots < this.limits.maxConcurrentAgents) {
        this.activeSlots += 1;
        return Promise.resolve();
      }
      return new Promise((resolve, reject) => {
        this.slotWaiters.push({
          resolve: () => {
            this.activeSlots += 1;
            resolve();
          },
          reject
        });
      });
    }
    releaseSlot() {
      this.activeSlots -= 1;
      const next = this.slotWaiters.shift();
      if (next) next.resolve();
    }
    /** The `agent(prompt, opts)` hook. */
    async agent(rawPrompt, rawOpts) {
      this.throwIfCancelled();
      if (typeof rawPrompt !== "string" || rawPrompt.length === 0) {
        throw new WorkflowError("agent() requires a non-empty prompt string", "INVALID_ARGUMENT");
      }
      const opts = this.readAgentOptions(rawOpts);
      if (this.started >= this.limits.maxTotalAgents) {
        throw new WorkflowError(
          `this run reached its total agent cap (${this.limits.maxTotalAgents}) \u2014 a runaway-loop backstop; raise the applicable maxTotalAgents limit if the scale is intentional`,
          "AGENT_CAP"
        );
      }
      this.started += 1;
      const seq = this.started;
      const label = opts.label ?? defaultLabel(rawPrompt);
      const phase = opts.phase ?? this.currentPhase;
      await this.acquireSlot();
      try {
        this.throwIfCancelled();
        let run;
        try {
          run = await this.children.startAgent({
            prompt: rawPrompt,
            ...opts.schema !== void 0 ? { schema: opts.schema } : {},
            ...opts.provider !== void 0 ? { provider: opts.provider } : {},
            ...opts.model !== void 0 ? { model: opts.model } : {}
          });
        } catch (error) {
          if (this.isCancelled()) throw this.cancelledError();
          throw new WorkflowError(`agent() could not start a child: ${renderThrown(error)}`, "AGENT_START", { cause: error });
        }
        if (this.isCancelled()) {
          await run.dispose();
          throw this.cancelledError();
        }
        const info = { seq, label, ...phase !== void 0 ? { phase } : {}, childId: SessionId(run.id) };
        this.observer.agentStart(info);
        try {
          let result;
          try {
            result = await run.result;
          } catch (error) {
            if (this.isCancelled()) {
              this.observer.agentEnd({ ...info, outcome: "cancelled" });
              throw this.cancelledError();
            }
            this.observer.agentEnd({ ...info, outcome: "failed" });
            throw new WorkflowError(`child agent run failed: ${renderThrown(error)}`, "AGENT_RESULT", { cause: error });
          }
          if (result.stopReason === "completed") {
            if (opts.schema !== void 0) {
              if (result.structured === void 0) {
                this.observer.agentEnd({ ...info, outcome: "failed" });
                return null;
              }
              this.observer.agentEnd({ ...info, outcome: "completed" });
              return result.structured;
            }
            this.observer.agentEnd({ ...info, outcome: "completed" });
            return outputText(result.output);
          }
          if (this.isCancelled()) {
            this.observer.agentEnd({ ...info, outcome: "cancelled" });
            throw this.cancelledError();
          }
          this.observer.agentEnd({ ...info, outcome: "failed" });
          return null;
        } finally {
          await run.dispose();
        }
      } finally {
        this.releaseSlot();
      }
    }
    /** Materialize + validate the `agent()` options bag from the realm. */
    readAgentOptions(rawOpts) {
      if (rawOpts === void 0) return {};
      let opts;
      try {
        opts = materializeFromRealm(rawOpts, "agent() options");
      } catch (error) {
        if (!(error instanceof MaterializeError)) throw error;
        throw new WorkflowError(`agent() options must be plain JSON data \u2014 ${error.message}`, "INVALID_ARGUMENT", { cause: error });
      }
      if (typeof opts !== "object" || opts === null || Array.isArray(opts)) {
        throw new WorkflowError("agent() options must be an object", "INVALID_ARGUMENT");
      }
      const record = opts;
      for (const key of Object.keys(record)) {
        if (SUPPORTED_AGENT_OPTIONS.has(key)) continue;
        if (DEFERRED_AGENT_OPTIONS.has(key)) {
          throw new WorkflowError(`agent() option "${key}" is deferred and not supported by this engine (supported: label, phase, schema, provider, model)`, "UNSUPPORTED_OPTION");
        }
        throw new WorkflowError(`agent() option "${key}" is not recognized (supported: label, phase, schema, provider, model)`, "UNSUPPORTED_OPTION");
      }
      for (const key of ["label", "phase", "provider", "model"]) {
        if (record[key] !== void 0 && typeof record[key] !== "string") {
          throw new WorkflowError(`agent() option "${key}" must be a string`, "INVALID_ARGUMENT");
        }
      }
      let schema;
      if (record.schema !== void 0) {
        try {
          assertObjectJsonSchema(record.schema);
          schema = record.schema;
        } catch (error) {
          if (!(error instanceof JsonSchemaError)) throw error;
          throw new WorkflowError(`agent() schema is outside the supported subset \u2014 ${error.message}`, "UNSUPPORTED_SCHEMA", { cause: error });
        }
      }
      return {
        ...record.label !== void 0 ? { label: record.label } : {},
        ...record.phase !== void 0 ? { phase: record.phase } : {},
        ...record.provider !== void 0 ? { provider: record.provider } : {},
        ...record.model !== void 0 ? { model: record.model } : {},
        ...schema !== void 0 ? { schema } : {}
      };
    }
    /** The `parallel(thunks)` hook: each thunk caught → `null`; fatal errors propagate. */
    async parallel(rawThunks) {
      this.throwIfCancelled();
      if (!Array.isArray(rawThunks)) {
        throw new WorkflowError("parallel() requires an array of zero-argument functions", "INVALID_ARGUMENT");
      }
      this.assertItemCap(rawThunks.length, "parallel()");
      const thunks = rawThunks.map((thunk, index) => {
        if (typeof thunk !== "function") {
          throw new WorkflowError(`parallel() item ${index} is not a function`, "INVALID_ARGUMENT");
        }
        return thunk;
      });
      return Promise.all(thunks.map(async (thunk) => {
        try {
          return await thunk();
        } catch (error) {
          if (isFatalWorkflowError(error)) throw error;
          return null;
        }
      }));
    }
    /** The `pipeline(items, ...stages)` hook: per-item stage chains, NO cross-stage barrier. */
    async pipeline(rawItems, rawStages) {
      this.throwIfCancelled();
      if (!Array.isArray(rawItems)) {
        throw new WorkflowError("pipeline() requires an items array", "INVALID_ARGUMENT");
      }
      this.assertItemCap(rawItems.length, "pipeline()");
      if (rawStages.length === 0) {
        throw new WorkflowError("pipeline() requires at least one stage function", "INVALID_ARGUMENT");
      }
      const stages = rawStages.map((stage, index) => {
        if (typeof stage !== "function") {
          throw new WorkflowError(`pipeline() stage ${index} is not a function`, "INVALID_ARGUMENT");
        }
        return stage;
      });
      return Promise.all(rawItems.map(async (item, index) => {
        let value = item;
        try {
          for (const stage of stages) {
            value = await stage(value, item, index);
          }
          return value;
        } catch (error) {
          if (isFatalWorkflowError(error)) throw error;
          return null;
        }
      }));
    }
    assertItemCap(length, hook) {
      if (length > this.limits.maxItemsPerCall) {
        throw new WorkflowError(
          `${hook} received ${length} items \u2014 over the per-call cap (${this.limits.maxItemsPerCall}); split the work or raise maxItemsPerCall in the engine config`,
          "ITEM_CAP"
        );
      }
    }
    /** The `phase(title)` hook: sets the current label for subsequent `agent()` calls and notifies observers. */
    phase(title) {
      this.throwIfCancelled();
      if (typeof title !== "string" || title.length === 0) {
        throw new WorkflowError("phase() requires a non-empty title string", "INVALID_ARGUMENT");
      }
      this.currentPhase = title;
      this.observer.phase(title);
    }
    /** The `log(message)` hook: narration to observers. */
    log(message) {
      this.throwIfCancelled();
      if (typeof message !== "string") {
        throw new WorkflowError("log() requires a message string", "INVALID_ARGUMENT");
      }
      this.observer.log(message);
    }
  };

  // reference/packages/workflow/workflow-worker-thread/src/session.ts
  var RpcChildHandle = class {
    constructor(post, callId, entry, id) {
      this.post = post;
      this.callId = callId;
      this.entry = entry;
      this.id = id;
      this.result = entry.settled.promise;
    }
    post;
    callId;
    entry;
    id;
    result;
    dispose() {
      this.post("child-dispose" /* ChildDispose */, { callId: this.callId });
      return this.entry.disposed.promise;
    }
  };
  var ChildRpcBridge = class {
    constructor(post) {
      this.post = post;
    }
    post;
    nextCallId = 0;
    pending = /* @__PURE__ */ new Map();
    async startAgent(request) {
      this.nextCallId += 1;
      const callId = this.nextCallId;
      const entry = {
        started: Promise.withResolvers(),
        settled: Promise.withResolvers(),
        disposed: Promise.withResolvers()
      };
      entry.settled.promise.catch(() => {
      });
      this.pending.set(callId, entry);
      this.post("child-start" /* ChildStart */, { callId, request });
      const childId = await entry.started.promise;
      return new RpcChildHandle(this.post, callId, entry, childId);
    }
    /** The host established a published child; releases the `startAgent` await. */
    onChildStarted(callId, childId) {
      this.pending.get(callId)?.started.resolve(childId);
    }
    /** Asynchronous provider start failed; reject and retire the pending RPC. */
    onChildStartError(callId, rendered) {
      const entry = this.pending.get(callId);
      this.pending.delete(callId);
      entry?.started.reject(new Error(rendered));
    }
    /** The child's terminal result arrived. */
    onChildSettled(callId, result) {
      this.pending.get(callId)?.settled.resolve(result);
    }
    /** The child's `result` rejected host-side (an infrastructure fault, relayed as fatal). */
    onChildFailed(callId, rendered) {
      this.pending.get(callId)?.settled.reject(new Error(rendered));
    }
    /** The host acked the dispose; the call's book-keeping is complete. */
    onChildDisposed(callId) {
      const entry = this.pending.get(callId);
      this.pending.delete(callId);
      entry?.disposed.resolve();
    }
  };
  async function runWorkerSession(port, init) {
    const post = (type, payload) => {
      port.postMessage({ type, ...payload });
    };
    const children = new ChildRpcBridge(post);
    const observer = {
      phase: (title) => {
        post("phase" /* Phase */, { title });
      },
      log: (message) => {
        post("log" /* Log */, { message });
      },
      agentStart: (info) => {
        post("agent-start" /* AgentStart */, { info });
      },
      agentEnd: (info) => {
        post("agent-end" /* AgentEnd */, { info });
      }
    };
    let execution;
    try {
      execution = new WorkflowExecution(init.meta, init.body, init.args, init.limits, observer, children);
    } catch (error) {
      post("result" /* Result */, { result: { value: null, stopReason: "error", error: renderThrown(error), agentsStarted: 0 } });
      return;
    }
    const gate = Promise.withResolvers();
    port.on("message", (message) => {
      switch (message.type) {
        case "go" /* Go */:
          gate.resolve();
          break;
        case "cancel" /* Cancel */:
          execution.cancel(message.reason);
          gate.resolve();
          break;
        case "child-started" /* ChildStarted */:
          children.onChildStarted(message.callId, message.childId);
          break;
        case "child-start-error" /* ChildStartError */:
          children.onChildStartError(message.callId, message.rendered);
          break;
        case "child-settled" /* ChildSettled */:
          children.onChildSettled(message.callId, message.result);
          break;
        case "child-failed" /* ChildFailed */:
          children.onChildFailed(message.callId, message.rendered);
          break;
        case "child-disposed" /* ChildDisposed */:
          children.onChildDisposed(message.callId);
          break;
        /* v8 ignore next 2 -- closed engine-owned union; the arm only makes adding a message type a compile error */
        default:
          assertNever(message, "host-to-worker message");
      }
    });
    post("ready" /* Ready */, {});
    await gate.promise;
    const result = await execution.drive();
    post("result" /* Result */, { result });
  }
  return __toCommonJS(entry_exports);
})();
