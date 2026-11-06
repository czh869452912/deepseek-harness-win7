import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

const root = process.cwd()
const { AclWriteGrant } = await import(pathToFileURL(resolve(root,
  'reference/packages/sandbox/sandbox-windows-acl/src/grant.ts')).href)
const { workspaceWriteSid } = await import(pathToFileURL(resolve(root,
  'reference/packages/sandbox/sandbox-windows-acl/src/workspace-sid.ts')).href)
const path = process.argv[2]
const sid = workspaceWriteSid(path)
const grant = AclWriteGrant.create(sid)
try {
  grant.add(path, true)
  console.log(JSON.stringify({ sid, granted: true, node: process.version }))
} finally {
  grant.dispose()
}
