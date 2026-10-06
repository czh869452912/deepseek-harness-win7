import {pathToFileURL} from 'node:url'
import {resolve} from 'node:path'

await import(pathToFileURL(resolve(process.env.DSH_SDK_SOURCE_ROOT!, 'apps/cli/src/bin.ts')).href)
