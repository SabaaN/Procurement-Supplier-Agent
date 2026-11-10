import { useState } from 'react'
import ProgressStrip from './components/ProgressStrip'
import ResultsTable from './components/ResultsTable'
import SearchForm from './components/SearchForm'
import SearchSummary from './components/SearchSummary'
import { useResults } from './hooks/useResults'
import { useSearchStream } from './hooks/useSearchStream'
import './App.css'

export default function App() {
  const [search, setSearch] = useState(null)
  const stream = useSearchStream(search ? search.id : null)
  const results = useResults(search ? search.id : null, stream.status)
  const finished = stream.status === 'done' || stream.status === 'failed'

  return (
    <div className="page">
      <header className="page__header">
        <h1>Procurement &amp; Supplier Agent</h1>
        <p>Find, compare and rank industrial devices against your requirements.</p>
      </header>

      <main className="page__main">
        {search ? (
          <SearchSummary search={search} onNew={() => setSearch(null)} />
        ) : (
          <SearchForm onStarted={setSearch} />
        )}

        {search && <ProgressStrip stream={stream} />}

        {search && finished && (
          <ResultsTable search={search} results={results} onToggleShortlist={results.toggleShortlist} />
        )}
      </main>
    </div>
  )
}