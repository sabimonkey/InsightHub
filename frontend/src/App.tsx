import { useCallback, useEffect, useState } from 'react'
import { ResearchNoteView } from './components/ux/ResearchNoteView'
import { AppShell, type AppView } from './layout/AppShell'
import { readNavFromLocation, writeNavToLocation, type AppNavState, type SettingsSection } from './lib/appNavigation'
import { AskPage } from './pages/AskPage'
import { BriefPage } from './pages/BriefPage'
import { InboxPage } from './pages/InboxPage'
import { LibraryPage } from './pages/LibraryPage'
import { SearchPage } from './pages/SearchPage'
import { SettingsPage } from './pages/SettingsPage'

function App() {
  const [nav, setNav] = useState<AppNavState>(() => readNavFromLocation())
  const [noteSourceId, setNoteSourceId] = useState<string | null>(null)

  const applyNav = useCallback((next: AppNavState, replace = false) => {
    setNav(next)
    writeNavToLocation(next, replace)
  }, [])

  useEffect(() => {
    const onPopState = () => setNav(readNavFromLocation())
    window.addEventListener('popstate', onPopState)
    applyNav(readNavFromLocation(), true)
    return () => window.removeEventListener('popstate', onPopState)
  }, [applyNav])

  function navigateView(view: AppView) {
    applyNav({
      view,
      librarySourceId: view === 'library' ? nav.librarySourceId : null,
      settingsSection: nav.settingsSection,
    })
  }

  function openLibrary(sourceId?: string | null) {
    applyNav({
      view: 'library',
      librarySourceId: sourceId ?? null,
      settingsSection: nav.settingsSection,
    })
  }

  function clearLibraryFocus() {
    if (!nav.librarySourceId) return
    applyNav({ ...nav, librarySourceId: null }, true)
  }

  function openNote(sourceId: string) {
    setNoteSourceId(sourceId)
  }

  function setSettingsSection(section: SettingsSection) {
    applyNav({ view: 'settings', librarySourceId: null, settingsSection: section })
  }

  return (
    <AppShell view={nav.view} onNavigate={navigateView}>
      {nav.view === 'inbox' ? (
        <InboxPage onOpenLibrary={(id) => openLibrary(id)} onViewAllLibrary={() => openLibrary(null)} />
      ) : null}
      {nav.view === 'library' ? (
        <LibraryPage
          focusSourceId={nav.librarySourceId}
          onFocusHandled={clearLibraryFocus}
          onOpenNote={openNote}
        />
      ) : null}
      {nav.view === 'search' ? <SearchPage onOpenNote={openNote} /> : null}
      {nav.view === 'ask' ? <AskPage onOpenNote={openNote} /> : null}
      {nav.view === 'briefs' ? <BriefPage onOpenNote={openNote} /> : null}
      {nav.view === 'settings' ? <SettingsPage section={nav.settingsSection} onSectionChange={setSettingsSection} /> : null}
      <ResearchNoteView
        key={noteSourceId ?? 'closed'}
        sourceId={noteSourceId}
        open={Boolean(noteSourceId)}
        onClose={() => setNoteSourceId(null)}
      />
    </AppShell>
  )
}

export default App
