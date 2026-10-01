// Installed Client SDK adapter. The authored async function body is evaluated
// by the pinned upstream evaluator, and its apply sees the upstream facade.
exports.inject = IDENTITY.placement === 'session' ? ['remote', 'sessions'] : ['remote'];
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
      } : field.codec.schema.type === 'boolean' ? value => {
        if (typeof value !== 'boolean') throw new Error('Host availability must be a boolean'); return value;
      } : json};
    }
  }
  const unmount = await ctx.remote.$mount({package: CONTRACT.package, descriptors});
  ctx.effect(() => unmount);
  const remote = ctx.get('remote.' + CONTRACT.invocations[0].namespace);
  async function load(owner, agentId, current = () => true, publish = () => {}) {
    const styles = new SDK.DynamicCordisStyles(IDENTITY.pluginId);
    let child, closed = false;
    const dispose = async () => {
      closed = true; styles.dispose();
      if (child) await child.dispose();
    };
    publish(dispose);
    try {
      const plugin = await SDK.evaluateClientHalf(IDENTITY.pluginId, CLIENT_SOURCE, {
        invoke: async (method, args) => {
          if (closed || !current()) throw new Error('exported Client activation ended');
          const reply = agentId === undefined ? await remote.call(method, args) : await remote.call(agentId, method, args);
          if (closed || !current()) throw new Error('exported Client activation ended');
          if (!reply.ok) throw new Error(reply.error.code + ': ' + reply.error.message);
          return reply.value;
        },
        noteError: message => { console.error('[python-export] ' + message); },
      }, styles);
      if (closed || !current()) { await dispose(); return dispose; }
      const ledger = [];
      let priority = 0;
      const apply = typeof plugin === 'function' ? plugin : plugin.apply;
      child = owner.plugin({
        name: IDENTITY.pluginId,
        inject: typeof plugin === 'function' ? [] : plugin.inject || [],
        apply: (child, config) => apply(SDK.dynamicCordisContext(child, {
          pkg: IDENTITY, ledger, claim: () => {}, allocatePriority: () => --priority,
          reportFailure: error => { console.error('[python-export] ' + error.message); },
        }), config),
      });
      await child.await();
      return dispose;
    } catch (error) { await dispose(); throw error; }
  }
  if (IDENTITY.placement !== 'session') {
    ctx.effect(() => load(ctx, undefined));
    return;
  }
  const sessions = ctx.sessions;
  let selected, epoch = 0, active = true, release;
  const tasks = new Set();
  function changed() {
    const snapshot = sessions.list.getSnapshot();
    const agentId = snapshot.currentAddress === undefined ? snapshot.current : undefined;
    if (agentId === selected) return;
    selected = agentId;
    const token = ++epoch;
    const drop = release; release = undefined;
    const dropping = drop ? drop() : undefined;
    // A previous availability request does not own the next selection.
    // Only the previous live fiber's disposal orders the new activation.
    const task = (async () => {
      await dropping;
      if (!active || token !== epoch || agentId === undefined) return;
      const reply = await remote.available(agentId);
      if (!active || token !== epoch) return;
      if (!reply.ok) throw new Error(reply.error.code + ': ' + reply.error.message);
      if (!reply.value) return;
      const scope = sessions.scope(agentId);
      if (!scope) return;
      const dispose = await load(scope, agentId, () => active && token === epoch, disposer => { release = disposer; });
      if (!active || token !== epoch) await dispose();
    })().catch(error => { if (active && token === epoch) console.error('[python-export] ' + error.message); });
    tasks.add(task);
    task.finally(() => tasks.delete(task));
  }
  const unsubscribe = sessions.list.subscribe(changed);
  ctx.effect(() => async () => {
    active = false; ++epoch; unsubscribe();
    const drop = release; release = undefined;
    if (drop) await drop();
    await Promise.all([...tasks]);
  });
  changed();
};
