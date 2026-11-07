return {
  inject: ['slots'],
  apply(ctx) {
    function Panel() {
      const [text, setText] = React.useState('中文 Win7');
      const [result, setResult] = React.useState('Ready');
      return React.createElement('section', {'data-win7-authoring': true},
        React.createElement('label', null, 'Echo text',
          React.createElement('input', {value: text, onChange: event => setText(event.target.value)})),
        React.createElement('button', {onClick: async () => {
          try { setResult(JSON.stringify(await host.call('echo', {text}))); }
          catch (error) { setResult(error.message); }
        }}, 'Call Python'),
        React.createElement('output', null, result));
    }
    ctx.slots.inject('tool.view.cordis', () => ctx.slots.register(
      {name: 'tool.view.cordis', key: 'self'}, Panel));
  },
};
