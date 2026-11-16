export function money(value, currency = '') {
  if (value == null) return '—'
  const digits = Math.abs(value) >= 1000 ? 0 : 2
  const text = Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return `${text} ${currency}`.trim()
}

export const scoreTone = (score) => (score >= 70 ? 'high' : score >= 40 ? 'mid' : 'low')

/** Only http(s) links are rendered as links: URLs come from the web. */
export function safeUrl(url) {
  return typeof url === 'string' && /^https?:\/\//i.test(url) ? url : null
}

export function hostname(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

export const supplierName = (p) => p.supplier || hostname(p.source_url) || 'Unknown supplier'

export const companyName = (p) => p.company_name || supplierName(p)

/** mailto:/tel: links only for values that look like an email / phone number (they come from the web). */
export const mailtoUrl = (email) =>
  typeof email === 'string' && /^[^\s@<>"]+@[^\s@<>"]+\.[a-z]{2,}$/i.test(email) ? `mailto:${email}` : null

export const telUrl = (phone) => {
  const digits = typeof phone === 'string' ? phone.replace(/[^\d+]/g, '') : ''
  return /^\+?\d{8,15}$/.test(digits) ? `tel:${digits}` : null
}