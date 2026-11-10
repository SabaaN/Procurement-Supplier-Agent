import { useState } from 'react'
import { keySpecs } from '../devices'
import { money, safeUrl, scoreTone, supplierName } from '../format'

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

export default function ResultRow({ product: p, deviceKey, currency, quantity, onToggle }) {
  const [open, setOpen] = useState(false)
  const link = safeUrl(p.source_url)
  const specs = keySpecs(deviceKey, p)
  const tone = scoreTone(p.match_score ?? 0)
  const met = p.requirements_met ?? []
  const missed = p.requirements_missed ?? []
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
          <div className="muted product__supplier">{supplierName(p)}</div>
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
          <td colSpan={7}>
            <div className="why__body">
              {p.explanation && <p className="why__text">{p.explanation}</p>}

              {(met.length > 0 || missed.length > 0) && (
                <div className="badges">
                  {met.map((m) => (
                    <span key={`met-${m}`} className="badge badge--met">
                      ✓ {m}
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