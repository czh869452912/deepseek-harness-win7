// Development-only oracle: extract the pinned literal with TypeScript's AST.
import ts from './official/node_modules/typescript/lib/typescript.js'
import { readFileSync } from 'node:fs'
import { Script, createContext } from 'node:vm'

const filename = 'reference/packages/workflow/tool-ralph/src/index.ts'
const source = ts.createSourceFile(filename, readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true)
let script
function visit(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'RALPH_SCRIPT') {
    const expression = node.initializer
    if (!ts.isTaggedTemplateExpression(expression) || expression.tag.getText(source) !== 'String.raw'
        || !ts.isNoSubstitutionTemplateLiteral(expression.template)) throw new Error('pinned Ralph script shape changed')
    script = expression.template.rawText
  }
  ts.forEachChild(node, visit)
}
visit(source)
if (script === undefined) throw new Error('pinned Ralph script missing')
script = script.replace(/\r\n/g, '\n')
if (readFileSync('dsh/workflow/ralph_script.js', 'utf8').replace(/\r\n/g, '\n') !== script) {
  throw new Error('native registration asset differs from pinned RALPH_SCRIPT')
}
let input = ''
for await (const chunk of process.stdin) input += chunk
const observations = []
for (const fixture of JSON.parse(input)) {
  const calls = [], phases = []
  const context = createContext({
    args: fixture.args,
    phase: title => phases.push(title),
    agent: async (prompt, opts) => {
      const report = fixture.reports[calls.length]
      calls.push(JSON.parse(JSON.stringify({ prompt, opts })))
      return structuredClone(report)
    },
  })
  const observation = { name: fixture.name, calls, phases }
  try {
    observation.value = await new Script(`(async () => {\n${script}\n})()`).runInContext(context)
  } catch (error) {
    observation.error = error.message
  }
  observations.push(observation)
}
process.stdout.write(JSON.stringify(observations))
