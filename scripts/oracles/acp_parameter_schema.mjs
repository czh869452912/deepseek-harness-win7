import * as source from './official/node_modules/@agentclientprotocol/sdk/dist/schema/zod.gen.js';
import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';

function fallback(value) {
  return value === undefined ? {absent: true} : typeof value === 'symbol' ? {skip: true} : {value};
}
function exportSchema(schema) {
  const definition = schema._zod.def;
  const result = {type: definition.type};
  switch (definition.type) {
    case 'object':
      result.shape = Object.fromEntries(Object.entries(definition.shape).map(([name, field]) => [name, exportSchema(field)]));
      break;
    case 'optional': case 'nullable':
      result.inner = exportSchema(definition.innerType);
      break;
    case 'catch':
      result.inner = exportSchema(definition.innerType);
      result.fallback = fallback(definition.catchValue({input: undefined, error: {issues: []}}));
      break;
    case 'default':
      result.inner = exportSchema(definition.innerType);
      result.fallback = fallback(definition.defaultValue);
      break;
    case 'array':
      result.element = exportSchema(definition.element);
      break;
    case 'record':
      result.key = exportSchema(definition.keyType);
      result.value = exportSchema(definition.valueType);
      break;
    case 'union':
      result.options = definition.options.map(exportSchema);
      break;
    case 'intersection':
      result.left = exportSchema(definition.left);
      result.right = exportSchema(definition.right);
      break;
    case 'literal':
      result.values = definition.values;
      break;
    case 'enum':
      result.values = Object.values(definition.entries);
      break;
    case 'number':
      if (definition.format) result.format = definition.format;
      result.checks = (definition.checks ?? []).map(check => check._zod.def);
      break;
    case 'pipe': {
      const transform = String(definition.out._zod.def.transform);
      if (transform.includes('items.filter')) {
        result.type = 'skip-array';
        result.inner = exportSchema(definition.in);
      } else if (transform.includes('Required value is missing')) {
        result.type = 'required-mcp-array';
        result.element = exportSchema(source.zMcpServer);
      } else throw new Error('Unsupported transform: ' + transform);
      break;
    }
    case 'unknown': case 'string': case 'boolean':
      break;
    default: throw new Error('Unsupported schema: ' + definition.type);
  }
  return result;
}
const names = {
  initialize: 'zInitializeRequest', authenticate: 'zAuthenticateRequest',
  'session/new': 'zNewSessionRequest', 'session/list': 'zListSessionsRequest',
  'session/resume': 'zResumeSessionRequest', 'session/close': 'zCloseSessionRequest',
  'session/set_config_option': 'zSetSessionConfigOptionRequest', 'session/prompt': 'zPromptRequest',
  'session/cancel': 'zCancelNotification',
};
const sdk = new URL('./official/node_modules/@agentclientprotocol/sdk/', import.meta.url);
const version = JSON.parse(readFileSync(new URL('package.json', sdk), 'utf8')).version;
if (version !== '1.4.0') throw new Error('ACP schema generator requires pinned SDK 1.4.0');
const digest = relative => createHash('sha256').update(readFileSync(new URL(relative, sdk))).digest('hex');
const payload = {sdkVersion: version, schemaSourceSha256: digest('dist/schema/zod.gen.js'),
  deserializeSourceSha256: digest('dist/schema-deserialize.js'),
  schemas: Object.fromEntries(Object.entries(names).map(([method, name]) => [method, exportSchema(source[name])]))};
const rendered = JSON.stringify(payload, null, 2) + '\n';
if (process.argv[2]) writeFileSync(process.argv[2], rendered);
else process.stdout.write(rendered);
