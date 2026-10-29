import type { AppView } from '../layout/AppShell'

export type SettingsSection = 'overview' | 'models' | 'routes' | 'runtime' | 'advanced'

export type AppNavState = {
  view: AppView
  librarySourceId: string | null
  settingsSection: SettingsSection
}

const VALID_VIEWS: AppView[] = ['inbox', 'library', 'search', 'ask', 'briefs', 'settings']
const VALID_SECTIONS: SettingsSection[] = ['overview', 'models', 'routes', 'runtime', 'advanced']

export function parseSettingsSection(raw: string | null): SettingsSection {
  if (raw && VALID_SECTIONS.includes(raw as SettingsSection)) {
    return raw as SettingsSection
  }
  return 'overview'
}

export function readNavFromLocation(location: Location = window.location): AppNavState {
  const params = new URLSearchParams(location.search)
  const viewRaw = params.get('view') ?? 'inbox'
  const view = VALID_VIEWS.includes(viewRaw as AppView) ? (viewRaw as AppView) : 'inbox'
  const librarySourceId = params.get('source')
  const settingsSection = parseSettingsSection(params.get('section'))
  return {
    view,
    librarySourceId: librarySourceId && librarySourceId.length > 8 ? librarySourceId : null,
    settingsSection,
  }
}

export function writeNavToLocation(state: AppNavState, replace = false): void {
  const params = new URLSearchParams()
  if (state.view !== 'inbox') {
    params.set('view', state.view)
  }
  if (state.view === 'library' && state.librarySourceId) {
    params.set('source', state.librarySourceId)
  }
  if (state.view === 'settings' && state.settingsSection !== 'overview') {
    params.set('section', state.settingsSection)
  }
  const query = params.toString()
  const url = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`
  if (replace) {
    window.history.replaceState(null, '', url)
  } else {
    window.history.pushState(null, '', url)
  }
}
