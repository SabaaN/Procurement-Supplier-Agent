export const KEY_SPECS = {
  camera: [
    { key: 'megapixels', format: (v) => `${v} MP` },
    { key: 'fps', format: (v) => `${v} fps` },
    { key: 'shutter', format: (v) => `${v} shutter` },
    { key: 'interface', format: (v) => v.join(' / ') },
  ],
  encoder: [
    { key: 'encoder_type', format: (v) => v },
    { key: 'ppr', format: (v) => `${v} PPR` },
    { key: 'resolution_bits', format: (v) => `${v}-bit` },
    { key: 'multiturn', format: (v) => (v ? 'multi-turn' : 'single-turn') },
    { key: 'shaft_type', format: (v) => `${v} shaft` },
    { key: 'shaft_diameter_mm', format: (v) => `Ø${v} mm` },
    { key: 'output', format: (v) => v.join(' / ') },
  ],
  photoelectric: [
    { key: 'sensing_method', format: (v) => v },
    { key: 'sensing_range_mm', format: (v) => (v >= 1000 ? `${v / 1000} m` : `${v} mm`) },
    { key: 'output', format: (v) => v.join(' / ') },
    { key: 'switching_mode', format: (v) => v.join(' / ') },
    { key: 'housing', format: (v) => v },
    { key: 'response_time_ms', format: (v) => `${v} ms` },
  ],
}

/** The spec texts to show for one product, skipping anything the page didn't state. */
export function keySpecs(deviceKey, product) {
  return (KEY_SPECS[deviceKey] ?? [])
    .filter((s) => {
      const v = product[s.key]
      return v != null && !(Array.isArray(v) && v.length === 0)
    })
    .map((s) => s.format(product[s.key]))
}