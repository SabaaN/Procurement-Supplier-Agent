import { useEffect, useReducer } from 'react'

export const STEPS = [
  { key: 'parse', label: 'Parse' },
  { key: 'search', label: 'Search' },
  { key: 'extract', label: 'Extract' },
  { key: 'filter', label: 'Filter' },
  { key: 'rank', label: 'Rank' },
]

const pending = () => ({ status: 'pending', message: '', done: null, total: null })

const initial = (running = false) => ({
  status: running ? 'running' : 'idle', // idle | running | done | failed
  attempt: 1,
  steps: Object.fromEntries(STEPS.map((s) => [s.key, pending()])),
  message: '',
  error: null,
  reconnecting: false,
})

function reducer(state, action) {
  switch (action.type) {
    case 'reset':
      return initial(action.running)

    case 'progress': {
      const e = action.event
      const index = STEPS.findIndex((s) => s.key === e.step)
      if (index === -1) return state

      const steps = { ...state.steps }
      let attempt = state.attempt
      // A step that was already done starts running again: the agent is retrying with broader
      // queries, so everything after it has to run again too.
      if (e.status === 'running' && steps[e.step].status === 'done') {
        if (e.step === 'search') attempt += 1
        STEPS.slice(index + 1).forEach((s) => {
          steps[s.key] = pending()
        })
      }
      steps[e.step] = { status: e.status, message: e.message, done: e.done, total: e.total }
      return { ...state, steps, attempt, message: e.message, reconnecting: false }
    }

    case 'end': {
      const steps = { ...state.steps }
      if (action.status === 'failed') {
        // whatever was running when it failed is where it failed
        for (const key of Object.keys(steps)) {
          if (steps[key].status === 'running') steps[key] = { ...steps[key], status: 'failed' }
        }
      }
      return { ...state, steps, status: action.status, error: action.error ?? null, reconnecting: false }
    }

    case 'reconnecting':
      return { ...state, reconnecting: true }
    case 'connected':
      return { ...state, reconnecting: false }
    case 'lost':
      return { ...state, status: 'failed', error: 'Lost the connection to the server.', reconnecting: false }

    default:
      return state
  }
}

/** Follows one search's live progress. Pass null to stay idle. */
export function useSearchStream(searchId) {
  const [state, dispatch] = useReducer(reducer, undefined, () => initial(false))

  useEffect(() => {
    dispatch({ type: 'reset', running: Boolean(searchId) })
    if (!searchId) return

    const source = new EventSource(`/api/searches/${searchId}/stream`)
    source.onopen = () => dispatch({ type: 'connected' })
    source.addEventListener('progress', (msg) => dispatch({ type: 'progress', event: JSON.parse(msg.data) }))
    source.addEventListener('end', (msg) => {
      dispatch({ type: 'end', ...JSON.parse(msg.data) })
      source.close() // the search is over: don't let the browser reconnect
    })
    source.onerror = () => {
      // CONNECTING means the browser is retrying by itself (and resumes via Last-Event-ID)
      if (source.readyState === EventSource.CLOSED) dispatch({ type: 'lost' })
      else dispatch({ type: 'reconnecting' })
    }
    return () => source.close()
  }, [searchId])

  return state
}