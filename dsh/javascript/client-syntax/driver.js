// Compile model code only. The worker's evaluated body is a fixed `return null`.
globalThis.__receive = () => {};
globalThis.__drive = async () => {
  let result;
  try {
    const wrapped = `(async () => {\n${__request.clientCode}\n})()`;
    // Match Function's ordinary function-body context, including new.target.
    // Match the current Node 24 grammar. Acorn 8.15 mistakes `await using;`
    // for a declaration; token lookahead distinguishes a binding identifier
    // from ordinary uses of the identifier without evaluating model code.
    const Parser = acorn.Parser.extend(Base => class extends Base {
      isAwaitUsing(isFor) {
        if (!super.isAwaitUsing(isFor)) return false;
        const lexer = acorn.tokenizer(this.input.slice(this.pos), { ecmaVersion: 'latest', locations: true });
        const keyword = lexer.getToken(), binding = lexer.getToken();
        return binding.type.label === 'name' && binding.loc.start.line === keyword.loc.end.line;
      }
    });
    Parser.parse(`function anonymous() {\n${wrapped}\n}`, { ecmaVersion: 'latest', locations: true });
    new Function(wrapped);
    result = { ok: true };
  } catch (error) {
    if (error.name !== 'SyntaxError') throw error;
    result = { ok: false, message: error.loc ? error.message.replace(/ \(\d+:\d+\)$/, '') : error.message,
      line: error.loc ? error.loc.line - 2 : null,
      column: error.loc ? error.loc.column : null };
  }
  __emit(JSON.stringify({ type: 'terminal', result }));
};
