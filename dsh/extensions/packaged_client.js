// Installed Client SDK adapter. The authored async function body is evaluated
// by the pinned upstream evaluator, and its apply sees the upstream facade.
exports.inject = ['remote'];
exports.apply = async function apply(ctx) {
  function json(value) {
    const root = {}, seen = new Set(), todo = [{value, holder: root, key: 'value'}];
    const set = (holder, key, value) => Object.defineProperty(holder, key, {value, enumerable: true, configurable: true, writable: true});
    while (todo.length) {
      const item = todo.pop(), current = item.value;
      if (item.leave) { seen.delete(current); continue; }
      if (current === null || typeof current === 'string' || typeof current === 'boolean') {set(item.holder, item.key, current); continue;}
      if (typeof current === 'number' && Number.isFinite(current) && !Object.is(current, -0)) {set(item.holder, item.key, current); continue;}
      if (!current || typeof current !== 'object' || seen.has(current)) throw new Error('host.call requires lossless JSON');
      const prototype = Object.getPrototypeOf(current);
      if (!Array.isArray(current) && prototype !== null && (Object.prototype.toString.call(current) !== '[object Object]' || Object.getPrototypeOf(prototype) !== null)) throw new Error('host.call requires a plain JSON object');
      if (Object.getOwnPropertySymbols(current).some(key => Object.prototype.propertyIsEnumerable.call(current, key))) throw new Error('host.call requires JSON string keys');
      if (Array.isArray(current) && Object.keys(current).length !== current.length) throw new Error('host.call requires a dense JSON array');
      if (Array.isArray(current)) for (let index = 0; index < current.length; index++) {
        if (!Object.prototype.hasOwnProperty.call(current, index)) throw new Error('host.call requires a dense JSON array');
      }
      const output = Array.isArray(current) ? [] : {};
      set(item.holder, item.key, output);
      seen.add(current); todo.push({value: current, leave: true});
      for (const key of Object.keys(current)) todo.push({value: current[key], holder: output, key});
    }
    return root.value;
  }
  const descriptors = JSON.parse(JSON.stringify(CONTRACT.invocations));
  for (const descriptor of descriptors) {
    for (const field of [...descriptor.parameters, {codec: descriptor.result}]) {
      field.codec.schema = {parse: field.codec.schema.type === 'string' ? value => {
        if (typeof value !== 'string') throw new Error('host.call method must be a string'); return value;
      } : json};
    }
  }
  const unmount = await ctx.remote.$mount({package: CONTRACT.package, descriptors});
  ctx.effect(() => unmount);
  const remote = ctx.get('remote.' + CONTRACT.invocations[0].namespace);
  const styles = new SDK.DynamicCordisStyles(IDENTITY.pluginId);
  ctx.effect(() => () => styles.dispose());
  const plugin = await SDK.evaluateClientHalf(IDENTITY.pluginId, CLIENT_SOURCE, {
    invoke: async (method, args) => {
      const reply = await remote.call(method, args);
      if (!reply.ok) throw new Error(reply.error.code + ': ' + reply.error.message);
      return reply.value;
    },
    noteError: message => { console.error('[python-export] ' + message); },
  }, styles);
  const ledger = [];
  let priority = 0;
  const apply = typeof plugin === 'function' ? plugin : plugin.apply;
  const child = ctx.plugin({
    name: IDENTITY.pluginId,
    inject: typeof plugin === 'function' ? [] : plugin.inject || [],
    apply: (child, config) => apply(SDK.dynamicCordisContext(child, {
      pkg: IDENTITY, ledger, claim: () => {}, allocatePriority: () => --priority,
      reportFailure: error => { console.error('[python-export] ' + error.message); },
    }), config),
  });
  await child.await();
};
