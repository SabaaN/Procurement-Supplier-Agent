import { STEPS } from '../hooks/useSearchStream'
import './ProgressStrip.css'

const SYMBOL = { done: '✓', failed: '!' }

export default function ProgressStrip({ stream }) {
  const { steps, status, message, attempt, error, reconnecting } = stream
  const current = STEPS.find((s) => steps[s.key].status === 'running')
  const counts = current ? steps[current.key] : null
  const percent = counts && counts.total ? Math.round((100 * counts.done) / counts.total) : null

  let line = message || 'Starting…'
  if (status === 'done') line = 'Finished'
  if (reconnecting) line = 'Connection lost, reconnecting…'

  return (
    <section className="card progress">
      <ol className="progress__steps">
        {STEPS.map((s) => (
          <li key={s.key} className={`step step--${steps[s.key].status}`}>
            <span className="step__dot" aria-hidden="true">
              {SYMBOL[steps[s.key].status]}
            </span>
            <span className="step__label">{s.label}</span>
          </li>
        ))}
      </ol>

      <p className="progress__message" aria-live="polite">
        {line}
      </p>

      {percent !== null && status === 'running' && (
        <div className="bar" role="progressbar" aria-valuenow={percent} aria-valuemin="0" aria-valuemax="100">
          <div className="bar__fill" style={{ width: `${percent}%` }} />
        </div>
      )}

      {attempt > 1 && (
        <p className="progress__note muted">
          Attempt {attempt}: too few matches, so the agent widened its search.
        </p>
      )}

      {error && (
        <p className="banner banner--error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}