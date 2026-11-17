// MiniSearch yields between 500-document chunks. The private worker has no I/O
// while indexing; a microtask preserves asynchronous chunk boundaries.
globalThis.setTimeout = callback => { Promise.resolve().then(callback); return 0; };
globalThis.clearTimeout = () => {};
globalThis.__receive = () => {};
globalThis.__drive = async () => {
  const rows = [];
  for (const operation of __request.operations) rows.push(await __marketIndex.observe(operation));
  __emit(JSON.stringify({ type: 'terminal', result: rows }));
};
