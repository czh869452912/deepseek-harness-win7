// The pure provider's optional schema warnings have no transport side effects.
globalThis.console = {log(){},warn(){},error(){}};
// V8 includes the pattern/flags and identifies an unfinished character class;
// QuickJS reports only "unexpected end". Preserve the observed SDK diagnostic
// for this unambiguous syntax failure without changing valid regexp behavior.
const NativeRegExp = RegExp;
globalThis.RegExp = new Proxy(NativeRegExp, {construct(target, args, receiver) {
  try { return Reflect.construct(target, args, receiver); }
  catch (error) {
    const pattern = String(args[0]), flags = args[1] === undefined ? '' : String(args[1]);
    let escaped = false, inClass = false;
    for (const character of pattern) {
      if (escaped) { escaped = false; continue; }
      if (character === '\\') { escaped = true; continue; }
      if (character === '[' && !inClass) inClass = true;
      else if (character === ']' && inClass) inClass = false;
    }
    if (error instanceof SyntaxError && error.message === 'unexpected end' && inClass) {
      error.message = 'Invalid regular expression: /' + pattern + '/' + flags + ': Unterminated character class';
    }
    throw error;
  }
}});
globalThis.__receive = () => {};
globalThis.__drive = () => new Promise(resolve => {
  globalThis.__receive = message => {
    if (message.type === 'stop') {
      __emit(JSON.stringify({type:'terminal', result:null}));resolve();return;
    }
    if (message.type !== 'validate') throw new Error('Invalid MCP validator request');
    __emit(JSON.stringify({type:'validation-result', id:message.id, result:__mcpValidator.observe(message.operation)}));
  };
});
