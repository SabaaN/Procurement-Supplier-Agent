import { useEffect, useState } from 'react'
import { ApiError, createSearch, getDeviceForm, getDevices } from '../api'
import { buildCriteria, fieldErrors } from '../criteria'
import FieldRow from './FieldRow'
import './SearchForm.css'

const CURRENCIES = ['PKR', 'USD', 'EUR', 'GBP', 'AED', 'CNY']

export default function SearchForm({ onStarted }) {
  const [devices, setDevices] = useState([])
  const [device, setDevice] = useState('')
  const [form, setForm] = useState(null) // { key, label, fields } for the chosen device
  const [values, setValues] = useState({})
  const [required, setRequired] = useState({})
  const [currency, setCurrency] = useState('PKR')
  const [notes, setNotes] = useState('')
  const [errors, setErrors] = useState({})
  const [message, setMessage] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  // The dropdown comes from the backend; the first enabled device is selected.
  useEffect(() => {
    getDevices()
      .then((list) => {
        setDevices(list)
        const first = list.find((d) => d.enabled)
        if (first) setDevice(first.key)
      })
      .catch((e) => setMessage(`Could not reach the server: ${e.message}`))
  }, [])

  // The inputs come from the backend too, per device.
  useEffect(() => {
    if (!device) return
    let cancelled = false
    setForm(null)
    setValues({})
    setRequired({})
    setErrors({})
    getDeviceForm(device)
      .then((f) => !cancelled && setForm(f))
      .catch((e) => !cancelled && setMessage(`Could not load the form: ${e.message}`))
    return () => {
      cancelled = true
    }
  }, [device])

  const setValue = (name, v) => {
    setValues((prev) => ({ ...prev, [name]: v }))
    setErrors((prev) => ({ ...prev, [name]: undefined }))
  }
  const setRequiredFlag = (name, flag) => setRequired((prev) => ({ ...prev, [name]: flag }))

  async function handleSubmit(e) {
    e.preventDefault()
    setErrors({})
    setMessage(null)
    setSubmitting(true)
    try {
      const criteria = buildCriteria({ fields: form.fields, values, required, currency, notes })
      const { id } = await createSearch(device, criteria)
            onStarted({ id, device, deviceLabel: form.label, fields: form.fields, criteria })
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setErrors(fieldErrors(err.detail))
        setMessage('Please fix the highlighted fields.')
      } else {
        setMessage(err.message)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const specFields = form ? form.fields.filter((f) => f.has_required_toggle) : []
  const budgetFields = form ? form.fields.filter((f) => !f.has_required_toggle) : []
  const rowProps = (f) => ({
    field: f,
    value: values[f.name],
    required: required[f.name],
    error: errors[f.name],
    onChange: setValue,
    onRequired: setRequiredFlag,
  })

  return (
    <form className="card form" onSubmit={handleSubmit} noValidate>
      <div className="form__device">
        <label htmlFor="device">Device type</label>
        <select id="device" value={device} onChange={(e) => setDevice(e.target.value)}>
          {devices.map((d) => (
            <option key={d.key} value={d.key} disabled={!d.enabled}>
              {d.label}
              {d.enabled ? '' : ' (coming soon)'}
            </option>
          ))}
        </select>
      </div>

      {!form && !message && <p className="muted">Loading form…</p>}

      {form && (
        <>
          <section className="form__section">
            <h2>Specifications</h2>
            <div className="form__grid">
              {specFields.map((f) => (
                <FieldRow key={f.name} {...rowProps(f)} />
              ))}
            </div>
          </section>

          <section className="form__section">
            <h2>Budget and quantity</h2>
            <div className="form__grid">
              <div className="field">
                <div className="field__head">
                  <label htmlFor="currency">Currency</label>
                </div>
                <select id="currency" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  {CURRENCIES.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </div>
              {budgetFields.map((f) => (
                <FieldRow key={f.name} {...rowProps(f)} />
              ))}
            </div>
          </section>

          <section className="form__section">
            <h2>Anything else?</h2>
            <textarea
              rows="3"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. must ship to Karachi, prefer authorised distributors"
            />
          </section>
        </>
      )}

      {message && (
        <p className="banner banner--error" role="alert">
          {message}
        </p>
      )}

      <div className="form__actions">
        <button className="btn btn--primary" type="submit" disabled={!form || submitting}>
          {submitting ? 'Starting…' : 'Find products'}
        </button>
      </div>
    </form>
  )
}