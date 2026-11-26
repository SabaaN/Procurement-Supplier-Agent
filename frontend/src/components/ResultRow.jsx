import { useState } from 'react'
import { downloadDatasheet } from '../api'
import { keySpecs } from '../devices'
import { companyName, hostname, mailtoUrl, money, safeUrl, scoreTone, telUrl } from '../format'

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

function Meter({ value, tone }) {
  return (
    <div className="meter">
      <div className={`meter__fill meter__fill--${tone}`} style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  )
}

export default function ResultRow({ product: p, searchId, showShipping, deviceKey, currency, quantity, onToggle }) {
  const link = safeUrl(p.product_link || p.source_url)
  const mailto = mailtoUrl(p.email)
  const tel = telUrl(p.contact_no)
  const specs = keySpecs(deviceKey, p)
  const tone = scoreTone(p.match_score ?? 0)
  const closeNotes = p.close_notes ?? []
  const misses = p.misses ?? []

  return (
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

      {showShipping && (
        <td className="cell cell--shipping" data-label="Shipping time">
          {p.shipping_time || <span className="muted">—</span>}
        </td>
      )}

      <td className="cell cell--specs" data-label="Key specs">
        {specs.length ? specs.join(' · ') : <span className="muted">—</span>}
      </td>
    </tr>
  )
}
