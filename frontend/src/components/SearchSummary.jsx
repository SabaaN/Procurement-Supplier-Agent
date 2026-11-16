import { summarizeCriteria } from '../criteria'
import './SearchSummary.css'

export default function SearchSummary({ search, onNew }) {
  const chips = summarizeCriteria(search.criteria, search.fields)
  return (
    <section className="card summary">
      <div className="summary__main">
        <strong>{search.deviceLabel}</strong>
        <ul className="summary__chips">
          {chips.map((c) => (
            <li key={c.text} className={c.required ? 'tag tag--required' : c.flexible ? 'tag tag--flexible' : 'tag'}>
              {c.text}
            </li>
          ))}
        </ul>
      </div>
      <button className="btn" type="button" onClick={onNew}>
        New search
      </button>
    </section>
  )
}