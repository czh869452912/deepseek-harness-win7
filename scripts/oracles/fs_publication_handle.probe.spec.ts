import {it} from 'vitest'
import {mkdtemp, readFile, readdir, rm, writeFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join, toNamespacedPath} from 'node:path'
import koffi from 'koffi'
import {writeFileAtomic} from '../../reference/packages/fs/fs-local/src/fsio.ts'

it('observes real original atomic publication with controlled delete sharing', async () => {
  const kernel = koffi.load('kernel32.dll')
  const open = kernel.func('void * __stdcall CreateFileW(const char16_t *path, uint32_t access, uint32_t sharing, void *security, uint32_t disposition, uint32_t attributes, void *template)')
  const close = kernel.func('int __stdcall CloseHandle(void *handle)')
  const lastError = kernel.func('uint32_t __stdcall GetLastError()')
  const rows: any[] = []
  const root = await mkdtemp(join(tmpdir(), 'source-fs-publication-'))
  try {
    for (const sharing of [3,7]) {
      const target = join(root, 'target-' + sharing)
      await writeFile(target, 'old')
      let handle: any
      let error: any = null
      try {
        await writeFileAtomic(target,'new',0o600,undefined,{inspectTemp:async () => {
          handle = open(toNamespacedPath(target),0x80000000,sharing,null,3,0x80,null)
          if (handle === null || handle === -1n) throw new Error('CreateFileW failed: ' + lastError())
        }})
      } catch (failure: any) {
        error = {win32Code:failure.win32Code ?? null, code:failure.code ?? null}
      } finally {
        if (handle && close(handle) === 0) throw new Error('CloseHandle failed: ' + lastError())
      }
      rows.push({sharing,error,content:await readFile(target,'utf8'),staging:(await readdir(root)).filter(name => name.endsWith('.tmpdir'))})
      await writeFileAtomic(target,'released',0o600,undefined)
      rows.push({sharing,released:true,content:await readFile(target,'utf8'),staging:(await readdir(root)).filter(name => name.endsWith('.tmpdir'))})
    }
    await writeFile(process.env.FS_PUBLICATION_RESEARCH_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
  } finally {
    await rm(root,{recursive:true,force:true})
  }
},15000)
