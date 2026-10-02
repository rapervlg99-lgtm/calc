import type { RollMark } from '../types/api'

export const LEGACY_STANDARD = '__legacy'

export function rollsForShape(roll: RollMark[], shape: string): RollMark[] {
  const base = shape.replace(/_$/, '')
  return roll.filter((r) => {
    // New bent-channel forms must not borrow geometry from rolled channels.
    if (['channel_bent', 'channel_unequal'].includes(shape)) return r.shape === shape
    if (['channel_bent', 'channel_unequal'].includes(r.shape)) return shape === 'channel_'
    return !r.shape || r.shape === shape || r.shape.startsWith(base) || shape.startsWith(r.shape.replace(/_$/, ''))
  })
}

export function standardOptions(roll: RollMark[]) {
  const seen = new Set<string>()
  const options: { value: string; label: string }[] = []
  for (const r of roll) {
    const value = r.standard || LEGACY_STANDARD
    if (seen.has(value)) continue
    seen.add(value)
    options.push({ value, label: r.standardLabel || r.standard || 'Прежний справочник' })
  }
  // Keep the source's current-before-archived order; legacy stays available.
  return options.sort((a, b) => Number(a.value === LEGACY_STANDARD) - Number(b.value === LEGACY_STANDARD))
}

export function rollsForStandard(roll: RollMark[], standard: string): RollMark[] {
  return roll.filter((r) => (r.standard || LEGACY_STANDARD) === standard)
}

export function assortmentLabel(r: RollMark): string {
  return r.familyLabel ? `${r.label} · ${r.familyLabel}` : r.label || r.id
}

export function sourceRollsForGost(roll: RollMark[], gost: string): RollMark[] {
  const text = gost.toUpperCase().replace(/[–—]/g, '-').replace(/\s+/g, '')
  return roll.filter((r) => {
    const code = (r.standard || '').match(/\d[\d.]*-\d{2,4}/)?.[0]
    return !!code && text.includes(code)
  })
}
