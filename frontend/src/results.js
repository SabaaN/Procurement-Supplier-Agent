export const FILTERS = [
  { key: 'starred', label: 'Starred', test: (p) => p.shortlisted },
  { key: 'priced', label: 'Has price', test: (p) => p.price_buyer != null },
  { key: 'clean', label: 'No warnings', test: (p) => (p.flags ?? []).length === 0 },
  { key: 'allmet', label: 'No missed specs', test: (p) => (p.requirements_missed ?? []).length === 0 },
]

export const SORT_OPTIONS = [
  { key: 'rank', label: 'Rank' },
  { key: 'score', label: 'Match score' },
  { key: 'price', label: 'Price' },
  { key: 'supplier', label: 'Supplier' },
  { key: 'title', label: 'Name' },
]

const VALUE = {
  rank: (p) => p.rank,
  score: (p) => p.match_score,
  price: (p) => p.price_buyer,
  supplier: (p) => (p.supplier || '').toLowerCase() || null,
  title: (p) => (p.title || '').toLowerCase(),
}

/** Products that pass every active filter (a Set of filter keys). */
export function filterProducts(products, active) {
  const tests = FILTERS.filter((f) => active.has(f.key)).map((f) => f.test)
  return products.filter((p) => tests.every((test) => test(p)))
}

/** Sorted copy. Missing values (e.g. no price) always go last, whichever direction. */
export function sortProducts(products, { key, dir }) {
  const get = VALUE[key]
  const factor = dir === 'asc' ? 1 : -1
  return [...products].sort((a, b) => {
    const x = get(a)
    const y = get(b)
    if (x == null && y == null) return 0
    if (x == null) return 1
    if (y == null) return -1
    return x < y ? -factor : x > y ? factor : 0
  })
}