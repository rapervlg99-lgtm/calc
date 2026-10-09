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

/** Родственные стандарты по данным gost-catalog-index кальклаба: одна форма
 * профиля в разных редакциях. Ключ — номер стандарта без года. */
const RELATED: Record<string, string[]> = {
  '20': ['57837', '35087', '8240'],   // СТО АСЧМ 20-93 → Р 57837-2017 / 35087-2024 / 8240
  '57837': ['20', '35087'],
  '35087': ['20', '57837'],
  '8240': ['20'],
}

/** Номер стандарта без года: «30245» из «ГОСТ 30245-2012», «20» из «СТО АСЧМ 20-93». */
export function standardNumber(standard: string): string {
  return (standard || '')
    .toUpperCase()
    .replace(/[–—]/g, '-')
    .replace(/\s+/g, '')
    .match(/(\d[\d.]*)-\d{2,4}/)?.[1] || ''
}

export function sourceRollsForGost(roll: RollMark[], gost: string, related = false): RollMark[] {
  const text = gost.toUpperCase().replace(/[–—]/g, '-').replace(/\s+/g, '')
  const exact = roll.filter((r) => {
    const code = (r.standard || '').match(/\d[\d.]*-\d{2,4}/)?.[0]
    return !!code && text.includes(code)
  })
  if (exact.length && !related) return exact
  // Правило редакций (решение Олега): лист ссылается на редакцию, которой в
  // сортаменте нет («ГОСТ 30245-2012» против 30245-2003, «ГОСТ 8240-97» против
  // 8240-2026). Профиль в редакциях тот же, поэтому массу берём из своей
  // редакции того же номера стандарта, а строку помечаем — редакция отличается.
  const num = standardNumber(text)
  if (!num) return []
  const base = exact.length ? exact : roll.filter((r) => standardNumber(r.standard || '') === num)
  // related=true — в дополнение к своим записям берём родственные редакции:
  // под «СТО АСЧМ 20-93» марок 45Ш4, 25Ш2, 22П, 27П нет, они есть только под
  // ГОСТ Р 57837-2017 и ГОСТ 8240-2026, а профиль тот же.
  if (!related) return base
  const family = RELATED[num] || []
  if (!family.length) return base
  return [...base, ...roll.filter((r) => family.includes(standardNumber(r.standard || '')))]
}
