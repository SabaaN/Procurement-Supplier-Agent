const isEmpty = (v) =>
  v === undefined || v === '' || v === false || (Array.isArray(v) && v.length === 0)

/** Form state -> the `criteria` object for POST /api/searches. Empty inputs are left out. */
export function buildCriteria({ fields, values, levels = {}, currency, notes, flexibleBudget = false }) {
  const criteria = { currency }
  if (notes.trim()) criteria.notes = notes.trim()

  for (const f of fields) {
    const v = values[f.name]
    if (isEmpty(v)) continue
    if (!f.has_required_toggle) {
      criteria[f.name] = Number(v) // budget and quantity are plain numbers
    } else {
      const level = levels[f.name] ?? 'nice'
      criteria[f.name] = {
        value: f.kind === 'number' ? Number(v) : v,
        required: level === 'must',
        flexible: level === 'flexible',
      }
    }
  }
  if (flexibleBudget && criteria.budget_max !== undefined) criteria.flexible_budget = true
  return criteria
}

/** The API's 422 detail ([{field, message}]) -> { fieldName: message }. */
export function fieldErrors(detail) {
  const out = {}
  if (!Array.isArray(detail)) return out
  for (const item of detail) {
    // our API sends {field, message}; FastAPI's own errors send {loc, msg}
    const field = item.field ?? (Array.isArray(item.loc) ? item.loc.filter((x) => x !== 'body' && x !== 'criteria').join('.') : '')
    const name = String(field ?? '').split('.')[0]
    out[name] ??= item.message ?? item.msg ?? 'Invalid value'
  }
  return out
}

/** The error text to show above the button: names the fields, and says what's wrong with any that
 * aren't on the form (so the message is never just "fix the highlighted fields" with nothing highlighted). */
export function errorSummary(errors, fields) {
  const labels = Object.fromEntries(fields.map((f) => [f.name, f.label]))
  const onForm = Object.keys(errors).filter((name) => labels[name])
  const elsewhere = Object.entries(errors).filter(([name]) => !labels[name])
  const parts = []
  if (onForm.length) parts.push(`Please fix: ${onForm.map((n) => labels[n]).join(', ')}.`)
  for (const [name, msg] of elsewhere) parts.push(name ? `${name}: ${msg}` : msg)
  return parts.join(' ') || 'The server rejected this search.'
}

const number = (n) => Number(n).toLocaleString()

/** The submitted criteria as chips for the collapsed form: [{ text, required, flexible }]. */
export function summarizeCriteria(criteria, fields) {
  const chips = []
  for (const f of fields) {
    const c = criteria[f.name]
    if (!f.has_required_toggle || !c) continue
    let text
    if (f.kind === 'number') {
      const bound = f.name.startsWith('min_') ? '≥ ' : f.name.startsWith('max_') ? '≤ ' : ''
      const prefix = bound && c.flexible ? '≈ ' : bound
      text = `${f.label} ${prefix}${number(c.value)}${f.unit ? ` ${f.unit}` : ''}`
    } else if (f.kind === 'multiselect') {
      text = `${f.label}: ${c.value.join(' / ')}`
    } else if (f.kind === 'toggle') {
      text = f.label
    } else {
      text = `${f.label}: ${c.value}`
    }
    chips.push({ text: c.flexible ? `${text} (flexible)` : text, required: c.required, flexible: c.flexible })
  }

  const { budget_min: lo, budget_max: hi, currency, quantity } = criteria
  if (lo !== undefined && hi !== undefined) {
    chips.push({ text: `Budget ${number(lo)}–${number(hi)} ${currency}`, required: true })
  } else if (hi !== undefined) {
    chips.push({ text: `Budget up to ${number(hi)} ${currency}`, required: true })
  } else if (lo !== undefined) {
    chips.push({ text: `Budget from ${number(lo)} ${currency}`, required: true })
  }
  if (criteria.flexible_budget) chips[chips.length - 1] = { text: `${chips.at(-1).text} (flexible)`, flexible: true }
  if (quantity !== undefined) chips.push({ text: `Qty ${number(quantity)}`, required: false })
  return chips
}