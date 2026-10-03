import { registerHooks } from 'node:module';

const sdk = new URL('./official/node_modules/@modelcontextprotocol/sdk/dist/esm/', import.meta.url);

registerHooks({resolve(specifier, context, nextResolve) {
  if (specifier === '@agentclientprotocol/sdk') {
    return nextResolve(new URL('./official/node_modules/@agentclientprotocol/sdk/dist/acp.js', import.meta.url).href, context);
  }
  if (specifier === 'zod') return nextResolve(new URL('./official/node_modules/zod/index.js', import.meta.url).href, context);
  if (specifier.startsWith('@modelcontextprotocol/sdk/')) {
    return nextResolve(new URL(specifier.slice('@modelcontextprotocol/sdk/'.length), sdk).href, context);
  }
  return nextResolve(specifier, context);
}});
