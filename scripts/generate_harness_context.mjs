/** Evaluate only literal static prompt expressions from the fixed TypeScript AST. */
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import {createRequire} from 'node:module'
const [source,output]=process.argv.slice(2),require=createRequire(path.resolve(source,'package.json')),ts=require('typescript')
const relative='packages/context/harness-dev-context/src/index.ts',bytes=fs.readFileSync(path.join(source,relative))
const file=ts.createSourceFile(relative,bytes.toString('utf8'),ts.ScriptTarget.Latest,true),declarations=new Map(),cache=new Map()
for(const statement of file.statements)if(ts.isVariableStatement(statement))for(const declaration of statement.declarationList.declarations)if(ts.isIdentifier(declaration.name))declarations.set(declaration.name.text,declaration.initializer)
function evaluate(node){
 if(ts.isStringLiteral(node)||ts.isNoSubstitutionTemplateLiteral(node))return node.text
 if(ts.isIdentifier(node)){if(!cache.has(node.text))cache.set(node.text,evaluate(declarations.get(node.text)));return cache.get(node.text)}
 if(ts.isBinaryExpression(node)&&node.operatorToken.kind===ts.SyntaxKind.PlusToken)return evaluate(node.left)+evaluate(node.right)
 if(ts.isTemplateExpression(node))return node.head.text+node.templateSpans.map(span=>evaluate(span.expression)+span.literal.text).join('')
 if(ts.isObjectLiteralExpression(node))return Object.fromEntries(node.properties.map(member=>{if(!ts.isPropertyAssignment(member))throw Error('nonliteral property');return [member.name.text,evaluate(member.initializer)]}))
 throw Error('unsupported static expression '+node?.getText(file))
}
const names=['HARNESS_SOURCE_PROMPT','WEB_SURFACE_PROMPT','LEGACY_SOURCE','LEGACY_WEB_SURFACE']
const constants=Object.fromEntries(names.map(name=>[name,evaluate(declarations.get(name))]))
fs.writeFileSync(output,JSON.stringify({upstream:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',source:relative,source_sha256:crypto.createHash('sha256').update(bytes).digest('hex'),constants},null,2)+'\n','utf8')
