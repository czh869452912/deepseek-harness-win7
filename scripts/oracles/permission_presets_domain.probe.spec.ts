import {it} from 'vitest'

it('observes actual permission defaults, seeds and numeric or empty table keys', async () => {
  await import('./permission_presets_domain_source.mts')
}, 30000)
