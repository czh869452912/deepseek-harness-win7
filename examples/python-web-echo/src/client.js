// Authored example body, wrapped into the original module-loader format by the
// development build script. React comes from the original shell shared module.
exports.inject = ['slots', 'remote'];
exports.apply = async function apply(ctx) {
  // The Python and browser faces share the exact declarative contract.
  function schema(spec) {
    return { parse(value) {
      if (spec.type === 'string' && typeof value === 'string') return value;
      if (spec.type === 'integer' && Number.isSafeInteger(value)) return value;
      if (spec.type === 'object' && value !== null && typeof value === 'object' && !Array.isArray(value)) {
        if (Object.keys(value).some(key => !(key in spec.properties))) throw new Error('Unknown Remote field');
        const result = {};
        for (const key of spec.required) result[key] = schema(spec.properties[key]).parse(value[key]);
        return result;
      }
      throw new Error('Remote value violates example contract');
    } };
  }
  const contribution = {package: CONTRACT.package, descriptors: JSON.parse(JSON.stringify(CONTRACT.invocations))};
  for (const invocation of contribution.descriptors) {
    for (const codec of [...invocation.parameters.map(value => value.codec), invocation.result]) codec.schema = schema(codec.schema);
  }
  const unmount = await ctx.remote.$mount(contribution);
  ctx.effect(() => unmount);
  const remote = ctx.get('remote.pythonWebEcho');
  function EchoPanel() {
    const [result, setResult] = React.useState('ready');
    const [input, setInput] = React.useState('中文 portable');
    return React.createElement('section', { 'data-python-web-echo': true, style: { position: 'fixed', top: 20, left: 800, zIndex: 999, pointerEvents: 'auto' } },
      React.createElement('input', { 'aria-label': 'Echo text', value: input, onChange: event => setInput(event.target.value) }),
      React.createElement('button', { 'data-python-web-echo-call': true, onClick: async () => {
        const reply = await remote.echo(input);
        setResult(JSON.stringify(reply));
      } }, 'Call installed Python plugin'),
      React.createElement('output', { 'data-python-web-echo-result': true }, result));
  }
  ctx.slots.inject('shell.overlay', () => ctx.slots.register({ name: 'shell.overlay', id: 'python-web-echo' }, EchoPanel));
};
