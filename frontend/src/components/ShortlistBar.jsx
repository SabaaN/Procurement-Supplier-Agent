import { exportUrl } from '../api'

export default function ShortlistBar({ searchId, count }) {
  return (
    <div className="shortlist" role="region" aria-label="Shortlist">
      <span>
        <strong>{count}</strong> starred
      </span>
      <div className="shortlist__actions">
        <a className="btn" href={exportUrl(searchId)} download>
          Export all (CSV)
        </a>
        {count > 0 ? (
          <a className="btn btn--primary" href={exportUrl(searchId, true)} download>
            Export shortlist (CSV)
          </a>
        ) : (
          <button className="btn btn--primary" type="button" disabled>
            Export shortlist (CSV)
          </button>
        )}
      </div>
    </div>
  )
}