// Private session protocol; all validation/search stays in the pinned bundle.
globalThis.__drive = () => new Promise(resolve => {
  const documents = new Map();
  let pending = 0, stopped = false;
  const finish = () => {
    if (stopped && pending === 0) {
      documents.clear();
      __emit(JSON.stringify({type:'terminal', result:null}));
      resolve();
    }
  };
  const retain = keys => {
    const live = new Set(keys);
    for (const key of documents.keys()) if (!live.has(key)) documents.delete(key);
  };
  globalThis.__receive = message => {
    if (message.type === 'stop') { stopped = true; finish(); return; }
    if (message.type === 'prune') { retain(message.keys); return; }
    if (message.type !== 'search' || stopped) throw new Error('Invalid Market search session message');
    retain(message.keys);
    let search = documents.get(message.key);
    if (!search) {
      search = __marketIndex.openSearch(message.index, message.url);
      documents.set(message.key, search);
    }
    pending++;
    Promise.resolve().then(() => search(message.selection)).then(
      names => __emit(JSON.stringify({type:'market-result', id:message.id, names})),
      error => __emit(JSON.stringify({type:'market-result', id:message.id, error:{name:error.name, message:error.message}})),
    ).finally(() => { pending--; finish(); });
  };
});
