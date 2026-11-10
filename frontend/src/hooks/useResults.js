import { useCallback, useEffect, useState } from 'react'
import { getResults, setShortlisted } from '../api'

/** Loads the ranked products once the search has finished, and handles starring. */
export function useResults(searchId, streamStatus) {
  const [state, setState] = useState({ products: [], loading: false, error: null })

  useEffect(() => {
    setState({ products: [], loading: false, error: null })
    if (!searchId || (streamStatus !== 'done' && streamStatus !== 'failed')) return
    let cancelled = false
    setState((s) => ({ ...s, loading: true }))
    getResults(searchId)
      .then((r) => !cancelled && setState({ products: r.products, loading: false, error: null }))
      .catch((e) => !cancelled && setState({ products: [], loading: false, error: e.message }))
    return () => {
      cancelled = true
    }
  }, [searchId, streamStatus])

  const toggleShortlist = useCallback(
    async (product) => {
      const next = !product.shortlisted
      const apply = (value) =>
        setState((s) => ({
          ...s,
          products: s.products.map((p) => (p.id === product.id ? { ...p, shortlisted: value } : p)),
        }))
      apply(next) // update the star straight away
      try {
        await setShortlisted(searchId, product.id, next)
      } catch (e) {
        apply(!next) // the save failed: put it back
        setState((s) => ({ ...s, error: `Could not update the shortlist: ${e.message}` }))
      }
    },
    [searchId],
  )

  return { ...state, toggleShortlist }
}