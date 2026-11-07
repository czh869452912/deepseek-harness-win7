styles.insert('[data-win7-authoring] { position: fixed; right: 16px; bottom: 16px; z-index: 999; background: white; color: black; padding: 12px; pointer-events: auto; }');
return {
  inject: ['slots'],
  apply(ctx) {
    function Panel() {
      const [result, setResult] = React.useState('Ready');
      return React.createElement('section', {'data-win7-authoring': true},
        React.createElement('button', {'data-win7-call': true, onClick: async () => {
          try { setResult(JSON.stringify(await host.call('echo', {text: '中文 Win7'}))); }
          catch (error) { setResult(error.message); }
        }}, 'Call Python'),
        React.createElement('output', {'data-win7-result': true}, result));
    }
    ctx.slots.inject('shell.overlay', () => ctx.slots.register(
      {name: 'shell.overlay', id: 'win7-authoring-echo'}, Panel));
  },
};
