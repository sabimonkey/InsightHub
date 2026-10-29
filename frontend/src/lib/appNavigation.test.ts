import { describe, expect, it } from 'vitest'
import { parseSettingsSection, readNavFromLocation } from './appNavigation'

describe('appNavigation', () => {
  it('reads library source from query', () => {
    const state = readNavFromLocation({
      ...window.location,
      search: '?view=library&source=11111111-1111-1111-1111-111111111111',
      pathname: '/',
      hash: '',
    } as Location)
    expect(state.view).toBe('library')
    expect(state.librarySourceId).toBe('11111111-1111-1111-1111-111111111111')
  })

  it('falls back invalid section to overview', () => {
    expect(parseSettingsSection('unknown')).toBe('overview')
    expect(parseSettingsSection('models')).toBe('models')
  })
})
