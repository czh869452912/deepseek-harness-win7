// Compile model code only. The worker's evaluated body is a fixed `return null`.
globalThis.__receive = () => {};
globalThis.__drive = async () => {
  let result;
  try {
    const wrapped = `(async () => {\n${__request.clientCode}\n})()`;
    // Match Function's ordinary function-body context, including new.target.
    // Disable the productions absent from the fixed Node 22.20 gate. Keep
    // newer syntax it accepts, such as dynamic-import options. These hooks
    // belong to the pinned, hash-checked Acorn version; do not scan source text.
    const Parser = acorn.Parser.extend(Base => class extends Base {
      isUsing() { return false; }
      isAwaitUsing() { return false; }
      regexp_eatModifiers(state) {
        const modifiers = super.regexp_eatModifiers(state);
        if (modifiers) state.raise('Invalid group');
        return modifiers;
      }
      regexp_groupSpecifier(state) {
        const start = state.pos;
        super.regexp_groupSpecifier(state);
        // Acorn normalizes escaped names and tracks disjoint alternatives.
        // The fixed V8 gate rejects repeated names even in separate branches.
        if (state.pos !== start && state.groupNames[state.lastStringValue].length > 1) {
          state.raise('Duplicate capture group name');
        }
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
