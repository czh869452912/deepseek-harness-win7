import { DatabaseSync } from 'node:sqlite'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { it } from 'vitest'
import { openSearchDatabase } from '../../reference/packages/session-query/session-query-sqlite/src/schema.ts'

it('observes actual derived schema, scoped data, reset and foreign database refusal', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dsh-query-schema-'))
  const rows: any[] = []
  const observe = async (name: string, operation: () => Promise<any>) => rows.push({name, observed: await operation()})
  try {
    await observe('memory-schema', async () => {
      const db = await openSearchDatabase(':memory:', 'wal')
      try {
        const names = ['live_sessions', 'persisted_sessions', 'search_state']
        return {application: db.prepare('PRAGMA application_id').get()!.application_id,
          version: db.prepare('PRAGMA user_version').get()!.user_version,
          strict: db.prepare('PRAGMA table_list').all().filter(row => names.includes(String(row.name)))
            .map(row => ({name: row.name, strict: row.strict})).sort((first, second) => String(first.name).localeCompare(String(second.name))),
          persistedColumns: db.prepare('PRAGMA table_info(persisted_docs)').all().map(row => row.name),
          liveColumns: db.prepare('PRAGMA temp.table_info(live_docs)').all().map(row => row.name)}
      } finally { db.close() }
    })
    for (const [name, sql] of [
      ['strict-type', "UPDATE search_state SET global_generation = 'bad'"],
      ['singleton-check', 'INSERT INTO search_state VALUES(2,0)'],
      ['live-check', "INSERT INTO temp.live_sessions(id,version,created_at,fingerprint,persisted,generation) VALUES('a',1,1,'f',2,1)"],
      ['strict-null', 'INSERT INTO persisted_sessions(id,version,created_at,revision,generation) VALUES(NULL,1,1,\'r\',1)'],
    ]) await observe(name, async () => {
      const db = await openSearchDatabase(':memory:', 'wal')
      try {
        let code = 0
        try { db.prepare(sql).run() } catch (error: any) { code = error.errcode }
        return {code, generation: db.prepare('SELECT global_generation FROM search_state').get()!.global_generation}
      } finally { db.close() }
    })
    await observe('memory-documents', async () => {
      const db = await openSearchDatabase(':memory:', 'wal')
      try {
        db.prepare('INSERT INTO persisted_docs VALUES(?,?,?,?,?,?,?)').run('café 中文 😀', 'session', 2, 'message', 5, 'current', 9)
        return {matches: db.prepare('SELECT session_id,codepoint_length FROM persisted_docs WHERE persisted_docs MATCH ?').all('cafe'),
          text: db.prepare('SELECT text FROM persisted_docs').get()!.text}
      } finally { db.close() }
    })
    for (const mode of ['wal', 'delete', 'truncate', 'persist'] as const) await observe('file-' + mode, async () => {
      const db = await openSearchDatabase(join(root, mode, '中文.sqlite'), mode)
      try { return {mode: db.prepare('PRAGMA journal_mode').get()!.journal_mode, version: db.prepare('PRAGMA user_version').get()!.user_version} }
      finally { db.close() }
    })
    for (const kind of ['reopen', 'upgrade', 'same-version', 'live-scope']) await observe(kind, async () => {
      const path = join(root, kind + '.sqlite')
      let db = await openSearchDatabase(path, 'delete')
      db.exec('UPDATE search_state SET global_generation = 7')
      db.prepare('INSERT INTO persisted_docs VALUES(?,?,?,?,?,?,?)').run('café 中文 😀', 'session', 2, 'message', 5, 'current', 9)
      db.prepare('INSERT INTO temp.live_docs VALUES(?,?,?,?,?,?,?)').run('live', 'session', 3, 'message', 6, 'current', 4)
      if (kind === 'upgrade') db.exec('PRAGMA user_version = 7')
      db.close()
      db = await openSearchDatabase(path, 'delete')
      try {
        return {generation: db.prepare('SELECT global_generation FROM search_state').get()!.global_generation,
          persisted: db.prepare('SELECT count(*) AS count FROM persisted_docs').get()!.count,
          live: db.prepare('SELECT count(*) AS count FROM temp.live_docs').get()!.count,
          matches: db.prepare('SELECT session_id FROM persisted_docs WHERE persisted_docs MATCH ?').all('cafe').map(row => row.session_id)}
      } finally { db.close() }
    })
    for (const kind of ['foreign-app', 'unmarked-nonempty', 'unknown-derived', 'canonical', 'corrupt']) await observe(kind, async () => {
      const path = join(root, kind + '.sqlite')
      if (kind === 'corrupt') await writeFile(path, 'not a SQLite database')
      else {
        const db = new DatabaseSync(path)
        db.exec('CREATE TABLE "sentinel"(value TEXT); INSERT INTO sentinel VALUES(\'owned\')')
        if (kind === 'foreign-app') db.exec('PRAGMA application_id = 1234')
        if (kind === 'unknown-derived') db.exec('PRAGMA application_id = 1146308689; PRAGMA user_version = 7')
        if (kind === 'canonical') db.exec('PRAGMA application_id = 1146308688; PRAGMA user_version = 19')
        db.close()
      }
      const before = createHash('sha256').update(await readFile(path)).digest('hex')
      let message = ''
      try { const db = await openSearchDatabase(path, 'wal'); db.close() } catch (error: any) { message = error.message.replaceAll(path, '<path>') }
      return {message, unchanged: before === createHash('sha256').update(await readFile(path)).digest('hex')}
    })
    await writeFile(process.env.QUERY_SCHEMA_OUTPUT!, JSON.stringify(rows, null, 2))
  } finally { await rm(root, {recursive: true, force: true}) }
})
