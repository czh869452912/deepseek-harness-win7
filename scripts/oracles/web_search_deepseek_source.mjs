import {readFile, writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const [root, fixture, output, endpoint] = process.argv.slice(2);
const {DeepSeekSearchProvider, mapAnthropicResponse} = await import(pathToFileURL(resolve(root,
  'packages/web/web-search-deepseek/src/provider.ts')).href);
const cases = JSON.parse(await readFile(fixture, 'utf8'));
const rows = [];
for (const entry of cases) {
  try { rows.push({name: entry.name, value: mapAnthropicResponse(entry.response)}); }
  catch (error) { rows.push({name: entry.name, error: {code: error.code, message: error.message}}); }
}
const availability = [];
for (const value of [0, -1, 1.5, true, 1, 32]) {
  const provider = new DeepSeekSearchProvider(() => ({apiKey: 'controlled-key', baseURL: 'https://api.test',
    model: 'controlled', apiVersion: '2023-06-01', maxTokens: value, maxUses: 1}));
  availability.push({maxTokens: value, available: provider.available()});
}
const options = {baseURL: 'https://unused.test', model: 'controlled', apiVersion: '2023-06-01',
  maxTokens: 32, maxUses: 1, apiKeyEnv: 'CONTROLLED_KEY'};
let missing;
try { await new DeepSeekSearchProvider(() => options).search({query: 'never dispatched'}); }
catch (error) { missing = {code: error.code, message: error.message}; }
const credentialErrors = [];
for (const signal of [undefined, new AbortController().signal]) {
for (const failure of [new Error('controlled credential failure'), new TypeError('controlled credential type')]) {
  try { await new DeepSeekSearchProvider(() => ({...options, resolveApiKey: () => Promise.reject(failure)}))
    .search({query: 'never dispatched'}, signal); }
  catch (error) { credentialErrors.push({code: error.code, message: error.message}); }
}
}
const decoding = [];
if (endpoint) for (const path of ['/bom', '/replacement', '/nan']) {
  try {
    const value = await new DeepSeekSearchProvider(() => ({...options, apiKey: 'controlled-search-key', baseURL: endpoint + path}))
      .search({query: 'controlled decoding'});
    decoding.push({path, value});
  } catch (error) { decoding.push({path, error: {code: error.code, message: error.message}}); }
}
await writeFile(output, JSON.stringify({rows, availability, missing, credentialErrors, decoding}, null, 2) + '\n', 'utf8');
