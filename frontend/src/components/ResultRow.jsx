import { useState } from 'react'
import { downloadDatasheet } from '../api'
import { keySpecs } from '../devices'
import { companyName, hostname, mailtoUrl, money, safeUrl, scoreTone, telUrl } from '../format'

const COLUMNS = 12 // keep in step with the headers in ResultsTable

/** Downloads the PDF through the backend; if that fails, says why and offers the original link. */
function DatasheetCell({ searchId, product }) {
  const [state, setState] = useState({ busy: false, error: null })
  const original = safeUrl(product.datasheet_url)
  if (!original) return <span className="muted">Not found</span>

  const download = async () => {
    setState({ busy: true, error: null })
    try {
      await downloadDatasheet(searchId, product.id)
      setState({ busy: false, error: null })
    } catch (e) {
      setState({ busy: false, error: e.message })
    }
  }

  return (
    <div className="datasheet">
      <button type="button" className="btn btn--sm" onClick={download} disabled={state.busy}>
        {state.busy ? 'Downloading…' : 'Download PDF'}
      </button>
      {state.error && (
        <span className="datasheet__error" role="alert">
          {state.error}
        </span>
      )}
      <a className="muted datasheet__link" href={original} target="_blank" rel="noreferrer noopener">
        {state.error ? 'Try opening it on the supplier site' : 'Open original'}
      </a>
    </div>
  )
}

const BREAKDOWN = {
  preferences: 'Preferred specs',
  price: 'Price',
  confidence: 'Data confidence',
}

function Meter({ value, tone }) {
  return (
    <div className="meter">
      <div className={`meter__fill meter__fill--${tone}`} style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  )
}

export default function ResultRow({ product: p, searchId, deviceKey, currency, quantity, onToggle }) {
  const [open, setOpen] = useState(false)
  const link = safeUrl(p.product_link || p.source_url)
  const mailto = mailtoUrl(p.email)
  const tel = telUrl(p.contact_no)
  const specs = keySpecs(deviceKey, p)
  const tone = scoreTone(p.match_score ?? 0)
  const met = p.requirements_met ?? []
  const missed = p.requirements_missed ?? []
  const close = p.requirements_close ?? []
  const closeNotes = p.close_notes ?? []
  const misses = p.misses ?? []
  const flags = p.flags ?? []

  return (
    <>
      <tr className={`row${p.shortlisted ? ' row--starred' : ''}`}>
        <td className="cell cell--star" data-label="">
          <button
            type="button"
            className={`star${p.shortlisted ? ' star--on' : ''}`}
            aria-pressed={p.shortlisted}
            aria-label={`${p.shortlisted ? 'Remove from' : 'Add to'} shortlist: ${p.title}`}
            onClick={() => onToggle(p)}
          >
            {p.shortlisted ? '★' : '☆'}
          </button>
        </td>

        <td className="cell cell--rank" data-label="Rank">
          {p.rank}
        </td>

        <td className="cell cell--product" data-label="">
          {link ? (
            <a className="product__title" href={link} target="_blank" rel="noreferrer noopener">
              {p.title}
            </a>
          ) : (
            <span className="product__title">{p.title}</span>
          )}
          {p.near_miss && misses.length > 0 && (
            <div className="nearmiss">Not an exact match: {misses.join('; ')}</div>
          )}
          {!p.near_miss && closeNotes.length > 0 && <div className="closenote">≈ {closeNotes.join('; ')}</div>}
        </td>

        <td className="cell cell--score" data-label="Match">
          <div className="score">
            <span className="score__num">{Math.round(p.match_score ?? 0)}</span>
            <Meter value={(p.match_score ?? 0) / 100} tone={tone} />
          </div>
        </td>

        <td className="cell cell--price" data-label="Price">
          {p.price_buyer != null ? (
            <>
              <div className="price__unit">{money(p.price_buyer, currency)}</div>
              {p.fx_rate && (
                <div className="muted price__note">
                  {money(p.price, p.currency)} at {p.fx_rate}
                </div>
              )}
              {p.total_cost != null && quantity > 1 && (
                <div className="muted price__note">
                  {quantity} units: {money(p.total_cost, currency)}
                </div>
              )}
            </>
          ) : p.price != null ? (
            <>
              <div className="price__unit">{money(p.price, p.currency)}</div>
              <div className="muted price__note">not converted</div>
            </>
          ) : (
            <span className="muted">No price found</span>
          )}
        </td>

        <td className="cell cell--company" data-label="Company name">
          {companyName(p)}
        </td>

        <td className="cell cell--contact" data-label="Email">
          {p.email ? mailto ? <a href={mailto}>{p.email}</a> : p.email : <span className="muted">—</span>}
        </td>

        <td className="cell cell--contact cell--phone" data-label="Contact no">
          {p.contact_no ? tel ? <a href={tel}>{p.contact_no}</a> : p.contact_no : <span className="muted">—</span>}
        </td>

        <td className="cell cell--link" data-label="Product link">
          {link ? (
            <a href={link} target="_blank" rel="noreferrer noopener" title={link}>
              {hostname(link) || 'Open'} ↗
            </a>
          ) : (
            <span className="muted">—</span>
          )}
        </td>

        <td className="cell cell--datasheet" data-label="Datasheet">
          <DatasheetCell searchId={searchId} product={p} />
        </td>

        <td className="cell cell--specs" data-label="Key specs">
          {specs.length ? specs.join(' · ') : <span className="muted">—</span>}
        </td>

        <td className="cell cell--toggle">
          <button
            type="button"
            className="btn why__toggle"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? 'Hide' : 'Why?'}
          </button>
        </td>
      </tr>

      {open && (
        <tr className="why">
          <td colSpan={COLUMNS}>
            <div className="why__body">
              {p.explanation && <p className="why__text">{p.explanation}</p>}

              {(met.length > 0 || missed.length > 0 || close.length > 0) && (
                <div className="badges">
                  {met.map((m) => (
                    <span key={`met-${m}`} className="badge badge--met">
                      ✓ {m}
                    </span>
                  ))}
                  {close.map((m) => (
                    <span key={`close-${m}`} className="badge badge--close">
                      ≈ {m}
                    </span>
                  ))}
                  {missed.map((m) => (
                    <span key={`missed-${m}`} className="badge badge--missed">
                      ✗ {m}
                    </span>
                  ))}
                </div>
              )}

              {flags.length > 0 && (
                <ul className="flags">
                  {flags.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              )}

              {p.score_breakdown && (
                <div className="breakdown">
                  {Object.entries(BREAKDOWN).map(([key, label]) => {
                    const v = p.score_breakdown[key]
                    return (
                      <div key={key} className="breakdown__item">
                        <span className="muted">{label}</span>
                        {v == null ? <span className="muted">not applicable</span> : <Meter value={v} tone={scoreTone(v * 100)} />}
                      </div>
                    )
                  })}
                </div>
              )}

              <p className="muted why__meta">
                {p.fetched_at && <>Page read {new Date(p.fetched_at).toLocaleString()}. </>}
                {link && (
                  <a href={link} target="_blank" rel="noreferrer noopener">
                    Open source page
                  </a>
                )}
              </p>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}