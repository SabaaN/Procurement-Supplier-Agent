import { useCallback, useEffect, useState } from 'react'

const parse = () => {
  const m = window.location.hash.match(/^#\/search\/([\w-]+)$/)
  return m ? m[1] : null
}

/** The search id from the URL, plus a setter that updates the URL (null clears it). */
export function useHashRoute() {
  const [id, setId] = useState(parse)

  useEffect(() => {
    const onChange = () => setId(parse())
    window.addEventListener('hashchange', onChange) // back/forward buttons, pasted links
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  const go = useCallback((next) => {
    // setting the hash fires "hashchange", which updates `id` above
    if (next == null) history.pushState(null, '', window.location.pathname + window.location.search)
    else window.location.hash = `/search/${next}`
    setId(next == null ? null : String(next))
  }, [])

  return [id, go]
}