import './FieldRow.css'

const hasValue = (v) =>
  !(v === undefined || v === '' || v === false || (Array.isArray(v) && v.length === 0))

const LEVELS = [
  { key: 'must', label: 'Must have', help: 'Dropped if the page shows it fails' },
  { key: 'flexible', label: 'Flexible', help: 'Close values are kept and ranked lower' },
  { key: 'nice', label: 'Nice to have', help: 'Only affects ranking' },
]

export default function FieldRow({ field, value, level = 'nice', error, onChange, onLevel }) {
  const id = `field-${field.name}`
  const labelId = `${id}-label`
  let control

  if (field.kind === 'number') {
    control = (
      <input
        id={id}
        type="number"
        min="0"
        step="any"
        value={value ?? ''}
        onChange={(e) => onChange(field.name, e.target.value)}
      />
    )
  } else if (field.kind === 'select') {
    control = (
      <select id={id} value={value ?? ''} onChange={(e) => onChange(field.name, e.target.value)}>
        <option value="">Any</option>
        {field.options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    )
  } else if (field.kind === 'multiselect') {
    const selected = Array.isArray(value) ? value : []
    const toggle = (o) =>
      onChange(field.name, selected.includes(o) ? selected.filter((x) => x !== o) : [...selected, o])
    control = (
      <div id={id} className="chips" role="group" aria-labelledby={labelId}>
        {field.options.map((o) => (
          <label key={o} className="chip">
            <input type="checkbox" checked={selected.includes(o)} onChange={() => toggle(o)} />
            {o}
          </label>
        ))}
      </div>
    )
  } else {
    control = (
      <label className="chip">
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(field.name, e.target.checked)}
        />
        Yes
      </label>
    )
  }

  return (
    <div className={`field${error ? ' field--error' : ''}`}>
      <div className="field__head">
        <label id={labelId} htmlFor={id}>
          {field.label}
          {field.unit && <span className="field__unit"> ({field.unit})</span>}
        </label>
      </div>
      {control}
      {field.has_required_toggle && hasValue(value) && (
        <div className="levels" role="radiogroup" aria-label={`How firm is ${field.label}?`}>
          {LEVELS.map((l) => (
            <label key={l.key} className={`level${level === l.key ? ' level--on' : ''}`} title={l.help}>
              <input
                type="radio"
                name={`${id}-level`}
                value={l.key}
                checked={level === l.key}
                onChange={() => onLevel(field.name, l.key)}
              />
              {l.label}
            </label>
          ))}
        </div>
      )}
      {field.help && <p className="field__help">{field.help}</p>}
      {error && (
        <p className="field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}