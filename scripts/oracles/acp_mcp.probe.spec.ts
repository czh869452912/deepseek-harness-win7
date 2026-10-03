import { writeFileSync } from 'node:fs'
import { expect, it } from 'vitest'
import { mountAcpMcpServers } from '../../reference/packages/acp/acp/src/mcp.ts'

it('observes complete declaration validation before mounting any provider', async () => {
  const stdio = {name: 'fixture', command: process.execPath, args: ['fixture.py'], env: []}
  const http = {type: 'http', name: 'web', url: 'https://example.test/mcp', headers: []}
  const inputs: any[][] = [[], [stdio], [http], [stdio, http], [stdio, stdio], [stdio, {...stdio, command: 'node'}]]
  for (const name of ['simple', '-', '_', 'a'.repeat(32), 'a'.repeat(33), 'Fancy server!', '!!!', 'é café', '中文', '😀', '\ud800', '   ', '\ufeff', '\u0085', 'bad\0', 'bad\x7f', 'bad\n']) inputs.push([{...stdio, name}])
  for (const env of [[{name: '__proto__', value: 'data'}], [{name: 'A', value: '1'}, {name: 'a', value: '2'}],
    [{name: 'A', value: '1'}, {name: 'A', value: '2'}], [{name: '', value: ''}], [{name: 'BAD=KEY', value: 'x'}],
    [{name: 'BAD\0', value: 'x'}], [{name: 'KEY', value: 'bad\0'}], [{name: 'KEY', value: ''}]]) inputs.push([{...stdio, env}])
  for (const headers of [[{name: '__proto__', value: 'data'}], [{name: 'X-Key', value: '1'}, {name: 'x-key', value: '2'}],
    [{name: 'bad name', value: 'x'}], [{name: '', value: 'x'}], [{name: 'x', value: '\t café'}],
    [{name: 'x', value: 'bad\n'}], [{name: 'x', value: '中文'}], [{name: 'x', value: '\x7f'}]]) inputs.push([{...http, headers}])
  for (const url of ['http://localhost/mcp', 'HTTPS://example.test', 'https:example.test/mcp', 'http:/localhost/mcp',
    'http:\\localhost\\mcp', ' https://example.test/mcp ', 'file:///tmp/mcp', '/relative', 'http://', 'http://bad host',
    'http://example.test:99999', 'http://[::1]/mcp', 'http://example.test:bad', 'http://example.test/%20']) inputs.push([{...http, url}])
  for (const type of ['sse', 'acp', 'stdio']) inputs.push([{...http, type}])
  inputs.push([{...stdio, args: [1]}], [{...http, headers: [{name: 'x', value: 1}]}])
  const observations = []
  for (const servers of inputs) {
    const mounted = []
    let result: any
    try {
      await mountAcpMcpServers({plugin: async (_provider, config) => {mounted.push(config)}} as any, servers as any, process.cwd())
      result = {data: mounted}
    } catch (error: any) {result = {name: error.name, message: error.message, mounted}}
    observations.push({servers, cwd: process.cwd(), result})
  }
  expect(observations.length).toBe(58)
  writeFileSync(process.env.ACP_MCP_OUTPUT!, JSON.stringify(observations, null, 2) + '\n')
})
