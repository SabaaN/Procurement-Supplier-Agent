const isEmpty = (v) =>
  v === undefined || v === '' || v === false || (Array.isArray(v) && v.length === 0)

/** Form state -> the `criteria` object for POST /api/searches. Empty inputs are left out. */
export function buildCriteria({ fields, values, required, currency, notes }) {
  const criteria = { currency }
  if (notes.trim()) criteria.notes = notes.trim()

  for (const f of fields) {
    const v = values[f.name]
    if (isEmpty(v)) continue
    if (!f.has_required_toggle) {
      criteria[f.name] = Number(v) // budget and quantity are plain numbers
    } else {
      criteria[f.name] = {
        value: f.kind === 'number' ? Number(v) : v,
        required: Boolean(required[f.name]),
      }
    }
  }
  return criteria
}

/** The API's 422 detail ([{field, message}]) -> { fieldName: message }. */
export function fieldErrors(detail) {
  const out = {}
  if (!Array.isArray(detail)) return out
  for (const { field, message } of detail) {
    const name = String(field).split('.')[0]
    out[name] ??= message
  }
  return out
}

const number = (n) => Number(n).toLocaleString()

/** The submitted criteria as chips for the collapsed form: [{ text, required }]. */
export function summarizeCriteria(criteria, fields) {
  const chips = []
  for (const f of fields) {
    const c = criteria[f.name]
    if (!f.has_required_toggle || !c) continue
    let text
    if (f.kind === 'number') {
      const prefix = f.name.startsWith('min_') ? '≥ ' : ''
      text = `${f.label} ${prefix}${number(c.value)}${f.unit ? ` ${f.unit}` : ''}`
    } else if (f.kind === 'multiselect') {
      text = `${f.label}: ${c.value.join(' / ')}`
    } else if (f.kind === 'toggle') {
      text = f.label
    } else {
      text = `${f.label}: ${c.value}`
    }
    chips.push({ text, required: c.required })
  }

  const { budget_min: lo, budget_max: hi, currency, quantity } = criteria
  if (lo !== undefined && hi !== undefined) {
    chips.push({ text: `Budget ${number(lo)}–${number(hi)} ${currency}`, required: true })
  } else if (hi !== undefined) {
    chips.push({ text: `Budget up to ${number(hi)} ${currency}`, required: true })
  } else if (lo !== undefined) {
    chips.push({ text: `Budget from ${number(lo)} ${currency}`, required: true })
  }
  if (quantity !== undefined) chips.push({ text: `Qty ${number(quantity)}`, required: false })
  return chips
}