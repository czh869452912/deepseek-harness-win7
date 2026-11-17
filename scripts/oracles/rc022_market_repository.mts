import { readFileSync } from 'node:fs'
import { load } from './rc022_subagent_fixture.mts'
const { repositoryOf, manifestRepository } = await load('packages/boot/plugin-market/src/detail.ts')
const rows = JSON.parse(readFileSync(process.argv[3], 'utf8')).map((operation: any) => {
  try { return { ok: true, value: (operation.kind === 'repository' ? repositoryOf(operation.value) : manifestRepository(operation.value)) ?? null } }
  catch (error: any) { return { ok: false, error: { name: error.name, message: error.message } } }
})
console.log(JSON.stringify(rows))
