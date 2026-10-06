import {it} from 'vitest'

it('observes actual permission settings, command and projection lifecycle', async () => {
  await import('./permission_presets_source.mts')
}, 30000)
