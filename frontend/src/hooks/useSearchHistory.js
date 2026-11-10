import { useEffect, useState } from 'react'
import { getSearches } from '../api'

/** Loads the list of past searches every time the panel is opened. */
export function useSearchHistory(open) {
  const [state, setState] = useState({ items: [], loading: false, error: null })

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    getSearches()
      .then((r) => {
        const items = Array.isArray(r) ? r : (r.searches ?? [])
        if (!cancelled) setState({ items, loading: false, error: null })
      })
      .catch((e) => !cancelled && setState({ items: [], loading: false, error: e.message }))
    return () => {
      cancelled = true
    }
  }, [open])

  return state
}