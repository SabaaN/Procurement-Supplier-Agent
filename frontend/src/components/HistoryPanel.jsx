import { useEffect } from 'react'
import { useSearchHistory } from '../hooks/useSearchHistory'
import './HistoryPanel.css'

const STATUS_LABEL = { done: 'Finished', failed: 'Failed', running: 'Running', pending: 'Running' }

function when(value) {
  if (!value) return ''
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

export default function HistoryPanel({ open, onClose, onPick, currentId }) {
  const { items, loading, error } = useSearchHistory(open)

  // Esc closes the panel
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      <div className="drawer__backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Search history">
        <div className="drawer__head">
          <h2>Past searches</h2>
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </div>

        {loading && <p className="muted">Loading…</p>}
        {error && (
          <p className="banner banner--error" role="alert">
            {error}
          </p>
        )}
        {!loading && !error && items.length === 0 && <p className="muted">No searches yet.</p>}

        <ul className="history">
          {items.map((s) => {
            const status = s.status ?? ''
            const budget = s.criteria?.budget_max
            return (
              <li key={s.id}>
                <button
                  type="button"
                  className={`history__item${String(s.id) === String(currentId) ? ' history__item--current' : ''}`}
                  onClick={() => onPick(s.id)}
                >
                  <span className="history__top">
                    <strong>{s.device_label ?? s.device ?? 'Search'} #{s.id}</strong>
                    <span className={`history__status history__status--${status}`}>
                      {STATUS_LABEL[status] ?? status}
                    </span>
                  </span>
                  <span className="muted history__meta">
                    {when(s.created_at)}
                    {budget != null && ` · budget up to ${budget} ${s.criteria?.currency ?? ''}`}
                    {s.product_count != null && ` · ${s.product_count} results`}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </aside>
    </>
  )
}