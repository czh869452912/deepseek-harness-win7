// The projector emits a pattern from V8's Object.prototype property order.
// Normalize only this private worker realm, keeping every original descriptor.
// Neither config objects nor the application's JavaScript runtime are modified.
const prototypeOrder = ['constructor', '__defineGetter__', '__defineSetter__', 'hasOwnProperty',
  '__lookupGetter__', '__lookupSetter__', 'isPrototypeOf', 'propertyIsEnumerable',
  'toString', 'valueOf', '__proto__', 'toLocaleString'];
const prototypeDescriptors = Object.getOwnPropertyDescriptors(Object.prototype);
if (Object.keys(prototypeDescriptors).length !== prototypeOrder.length
  || prototypeOrder.some(key => !Object.hasOwn(prototypeDescriptors, key))) throw Error('Config projector intrinsic surface differs');
for (const key of prototypeOrder) delete Object.prototype[key];
for (const key of prototypeOrder) Object.defineProperty(Object.prototype, key, prototypeDescriptors[key]);
globalThis.__receive = () => {};
globalThis.__drive = async () => {
  if (__request.nativeGraph) {
    let pending;
    const state = __configProjection.createGraphState(index => new Promise((resolve, reject) => {
      if (pending) throw Error('overlapping Config builder requests');
      pending = { index, resolve, reject };
      __emit(JSON.stringify({ type: 'config-builder', index }));
    }));
    globalThis.__receive = message => {
      if (message.type === 'cancel') {
        if (pending) { pending.reject(Error(message.reason)); pending = undefined; }
        return;
      }
      if (message.type !== 'config-builder-result' || !pending || pending.index !== message.index) throw Error('unexpected Config builder response');
      const current = pending; pending = undefined;
      if (Object.hasOwn(message, 'error')) current.reject(Error(message.error));
      else { state.merge(message.graph); current.resolve(state.decode(message.value)); }
    };
    try {
      const [root] = state.merge(__request.nativeGraph);
      const project = await __configProjection.createAsyncConfigProjector();
      const value = await project(root, __request.prefix);
      __emit(JSON.stringify({ type: 'terminal', result: { ok: true, value } }));
    } catch (error) {
      __emit(JSON.stringify({ type: 'terminal', result: { ok: false, error: error.message } }));
    }
    return;
  }
  const rows = [];
  for (const entry of __request.graphs) {
    const wire = { ...entry, builderCalls: [] };
    try {
      const roots = __configProjection.decodeGraph(wire);
      const project = await (__request.asyncProjection ? __configProjection.createAsyncConfigProjector() : __configProjection.createConfigProjector());
      const results = [];
      for (const [index, root] of roots.entries()) {
        try { results.push({ value: await project(root, 'graph' + index) }); }
        catch (error) { results.push({ error: error.message }); }
      }
      rows.push({ results, builderCalls: wire.builderCalls });
    } catch (error) {
      rows.push({ error: error.message, builderCalls: wire.builderCalls });
    }
  }
  __emit(JSON.stringify({ type: 'terminal', result: rows }));
};
