import { useMemo, useState } from 'react'
import { FILTERS, SORT_OPTIONS, filterProducts, sortProducts } from '../results'
import ResultRow from './ResultRow'
import ShortlistBar from './ShortlistBar'
import './ResultsTable.css'

const HEADERS = [
  { key: 'rank', label: '#' },
  { key: 'title', label: 'Product' },
  { key: 'score', label: 'Match' },
  { key: 'price', label: 'Price' },
  { key: 'supplier', label: 'Company name' },
]
const DEFAULT_DIR = { score: 'desc' } // best first; everything else starts ascending

export default function ResultsTable({ search, results, onToggleShortlist }) {
  const { products, loading, error } = results
  const [sort, setSort] = useState({ key: 'rank', dir: 'asc' })
  const [active, setActive] = useState(() => new Set())

  const shown = useMemo(() => sortProducts(filterProducts(products, active), sort), [products, active, sort])
  const starred = products.filter((p) => p.shortlisted).length
  const currency = search.criteria.currency
  const quantity = search.criteria.quantity ?? 1
  const converted = products.some((p) => p.fx_rate)

  const toggleSort = (key) =>
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: DEFAULT_DIR[key] ?? 'asc' },
    )
  const toggleFilter = (key) =>
    setActive((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  const ariaSort = (key) => (sort.key !== key ? 'none' : sort.dir === 'asc' ? 'ascending' : 'descending')

  if (loading) return <section className="card muted">Loading results…</section>

  return (
    <section className="results">
      {error && (
        <p className="banner banner--error" role="alert">
          {error}
        </p>
      )}

      {products.length === 0 ? (
        !error && (
          <div className="card">
            <strong>No products found.</strong>
            <p className="muted">
              The agent couldn't read any matching product pages. Try marking specs as Flexible, or setting a
              flexible budget.
            </p>
          </div>
        )
      ) : (
        <>
          {products.every((p) => p.near_miss) && (
            <div className="banner banner--warn" role="status">
              <strong>No exact matches – these are the closest options.</strong> Each one says what it misses.
              Mark that spec as Flexible, or widen the budget, to search around it.
            </div>
          )}
          <div className="results__toolbar">
            <h2 className="results__title">
              {shown.length === products.length ? `${products.length} products` : `${shown.length} of ${products.length} products`}
            </h2>

            <div className="filters" role="group" aria-label="Filters">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  className="filter"
                  aria-pressed={active.has(f.key)}
                  onClick={() => toggleFilter(f.key)}
                >
                  {f.label}
                </button>
              ))}
            </div>

            {/* phones have no clickable headers, so they sort from here */}
            <label className="sortpick">
              Sort by
              <select
                value={`${sort.key}:${sort.dir}`}
                onChange={(e) => {
                  const [key, dir] = e.target.value.split(':')
                  setSort({ key, dir })
                }}
              >
                {SORT_OPTIONS.flatMap((o) => [
                  <option key={`${o.key}:asc`} value={`${o.key}:asc`}>{`${o.label} (low to high)`}</option>,
                  <option key={`${o.key}:desc`} value={`${o.key}:desc`}>{`${o.label} (high to low)`}</option>,
                ])}
              </select>
            </label>
          </div>

          <div className="card table-card">
            <table className="table">
              <thead>
                <tr>
                  <th aria-label="Shortlist" />
                  {HEADERS.slice(0, 2).map((h) => (
                    <th key={h.key} aria-sort={ariaSort(h.key)}>
                      <button type="button" className="th-btn" onClick={() => toggleSort(h.key)}>
                        {h.label}
                        {sort.key === h.key && <span aria-hidden="true">{sort.dir === 'asc' ? ' ▲' : ' ▼'}</span>}
                      </button>
                    </th>
                  ))}
                  {HEADERS.slice(2).map((h) => (
                    <th key={h.key} aria-sort={ariaSort(h.key)}>
                      <button type="button" className="th-btn" onClick={() => toggleSort(h.key)}>
                        {h.label}
                        {sort.key === h.key && <span aria-hidden="true">{sort.dir === 'asc' ? ' ▲' : ' ▼'}</span>}
                      </button>
                    </th>
                  ))}
                  <th>Email</th>
                  <th>Contact no</th>
                  <th>Product link</th>
                  <th>Datasheet</th>
                  <th>Key specs</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((p) => (
                  <ResultRow
                    key={p.id}
                    product={p}
                    searchId={search.id}
                    deviceKey={search.device}
                    currency={currency}
                    quantity={quantity}
                    onToggle={onToggleShortlist}
                  />
                ))}
              </tbody>
            </table>
            {shown.length === 0 && <p className="muted results__empty">No products match these filters.</p>}
          </div>

          <ShortlistBar searchId={search.id} count={starred} />

          {converted && (
            <p className="muted results__credit">
              Exchange rates by <a href="https://www.exchangerate-api.com">Rates By Exchange Rate API</a>.
            </p>
          )}
        </>
      )}
    </section>
  )
}