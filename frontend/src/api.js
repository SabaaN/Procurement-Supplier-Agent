export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : 'Request failed')
    this.status = status
    this.detail = detail // a string, or a list of {field, message} for form errors
  }
}

async function request(path, options) {
  const res = await fetch(path, options)
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* the error body wasn't JSON */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json()
}

export const getDevices = () => request('/api/devices')
export const getDeviceForm = (key) => request(`/api/devices/${key}`)

export const createSearch = (deviceType, criteria) =>
  request('/api/searches', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_type: deviceType, criteria }),
  })

export const getResults = (id) => request(`/api/searches/${id}/results`)

export const setShortlisted = (id, productId, shortlisted) =>
  request(`/api/searches/${id}/shortlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_id: productId, shortlisted }),
  })

export const exportUrl = (id, shortlistOnly = false) =>
  `/api/searches/${id}/export.csv${shortlistOnly ? '?shortlist_only=true' : ''}`

export const datasheetUrl = (id, productId) => `/api/searches/${id}/products/${productId}/datasheet`

/** Downloads a product's datasheet PDF through the backend. Resolves to the file name, or throws ApiError. */
export async function downloadDatasheet(id, productId) {
  const res = await fetch(datasheetUrl(id, productId))
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* the error body wasn't JSON */
    }
    throw new ApiError(res.status, detail)
  }
  const match = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')
  const name = match ? match[1] : 'datasheet.pdf'
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
  return name
}

export const getSearches = () => request('/api/searches')

export const getSearch = (id) => request(`/api/searches/${id}`)