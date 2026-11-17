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
  const rows = [];
  for (const entry of __request.graphs) {
    const wire = { ...entry, builderCalls: [] };
    try {
      const roots = __configProjection.decodeGraph(wire);
      const project = await __configProjection.createConfigProjector();
      const results = roots.map((root, index) => {
        try { return { value: project(root, 'graph' + index) }; }
        catch (error) { return { error: error.message }; }
      });
      rows.push({ results, builderCalls: wire.builderCalls });
    } catch (error) {
      rows.push({ error: error.message, builderCalls: wire.builderCalls });
    }
  }
  __emit(JSON.stringify({ type: 'terminal', result: rows }));
};
