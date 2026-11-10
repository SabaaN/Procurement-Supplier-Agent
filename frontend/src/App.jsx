import { useCallback, useEffect, useState } from 'react'
import { getDeviceForm, getSearch } from './api'
import HistoryPanel from './components/HistoryPanel'
import ProgressStrip from './components/ProgressStrip'
import ResultsTable from './components/ResultsTable'
import SearchForm from './components/SearchForm'
import SearchSummary from './components/SearchSummary'
import { useHashRoute } from './hooks/useHashRoute'
import { useResults } from './hooks/useResults'
import { useSearchStream } from './hooks/useSearchStream'
import './App.css'

export default function App() {
  const [urlId, go] = useHashRoute()
  const [search, setSearch] = useState(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [loadError, setLoadError] = useState(null)

  const stream = useSearchStream(search ? search.id : null)
  const results = useResults(search ? search.id : null, stream.status)
  const finished = stream.status === 'done' || stream.status === 'failed'

  // The URL is the source of truth: whenever its id changes, show that search.
  useEffect(() => {
    setLoadError(null)
    if (urlId == null) {
      setSearch(null)
      return
    }
    if (search && String(search.id) === String(urlId)) return // already showing it
    let cancelled = false
    ;(async () => {
      try {
        const saved = await getSearch(urlId)
        const device = saved.device ?? saved.device_type
        const form = await getDeviceForm(device)
        if (cancelled) return
        setSearch({
          id: saved.id ?? urlId,
          device,
          deviceLabel: form.label ?? device,
          fields: form.fields,
          criteria: saved.criteria ?? saved.raw_criteria ?? {},
        })
      } catch (e) {
        if (cancelled) return
        setLoadError(`Could not open search #${urlId}: ${e.message}`)
        setSearch(null)
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlId])

  // A new search from the form: remember it in the URL too.
  const started = useCallback(
    (s) => {
      setSearch(s)
      go(s.id)
    },
    [go],
  )

  const openFromHistory = (id) => {
    setHistoryOpen(false)
    go(id)
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Procurement &amp; Supplier Agent</h1>
          <p>Find, compare and rank industrial devices against your requirements.</p>
        </div>
        <button type="button" className="btn" onClick={() => setHistoryOpen(true)}>
          Past searches
        </button>
      </header>

      <main className="page__main">
        {loadError && (
          <p className="banner banner--error" role="alert">
            {loadError}
          </p>
        )}

        {search ? (
          <SearchSummary search={search} onNew={() => go(null)} />
        ) : (
          <SearchForm onStarted={started} />
        )}

        {search && <ProgressStrip stream={stream} />}

        {search && finished && (
          <ResultsTable search={search} results={results} onToggleShortlist={results.toggleShortlist} />
        )}
      </main>

      <HistoryPanel
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onPick={openFromHistory}
        currentId={search ? search.id : null}
      />
    </div>
  )
}