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