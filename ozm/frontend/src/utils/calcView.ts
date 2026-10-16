/** Форматирование результатов расчёта для отображения (чистые функции). */
import type { ElementResult } from '../types/api'

export function fmt(n: number | null | undefined, digits: number): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** Способ облицовки из ответа бэкенда: 1 короб, 2 контур, 3 по трубе. */
export function liningLabel(lining: number): string {
  switch (lining) {
    case 1: return 'Короб'
    case 2: return 'Контур'
    case 3: return 'По трубе'
    default: return '—'
  }
}

export function isTaikor(coat: string): boolean {
  return coat === '2' || coat === '3' || coat === '4'
}

/** АКЗ — только антикоррозионная защита: конструкция считается, но огнезащиты в ней нет. */
export function isAkz(coat: string): boolean {
  return coat === '1.5'
}

/** Толщина покрытия: ОЗМ — целые мм плиты, TAIKOR — мм состава с сотыми. */
export function resultDelta(r: ElementResult): string {
  if (r.exclusion || isAkz(r.coat)) return '—'
  return isTaikor(r.coat) ? fmt(r.delta, 2) : fmt(r.delta, 0)
}

/** Объём (ОЗМ, м³) или масса (TAIKOR, кг); бэкенд хранит оба в поле volume. */
export function resultOutput(r: ElementResult): string {
  if (isAkz(r.coat)) return '—' // у АКЗ огнезащитного расхода нет — только площадь
  if (r.exclusion) return 'не достигается'
  return isTaikor(r.coat) ? `${fmt(r.volume, 1)} кг` : `${fmt(r.volume, 3)} м³`
}

export interface ResultTotals {
  area: number
  volumeM3: number
  massKg: number
  exclusions: number
}

/**
 * Итоги огнезащиты по элементам. Конструкции только с АКЗ в них не входят: их
 * площадь — площадь антикоррозионной окраски, а не огнезащиты, и материала
 * огнезащиты у них нет. В самой строке результата площадь видна.
 */
export function totalsOf(rows: ElementResult[]): ResultTotals {
  const t: ResultTotals = { area: 0, volumeM3: 0, massKg: 0, exclusions: 0 }
  for (const r of rows) {
    if (r.exclusion) t.exclusions++
    if (isAkz(r.coat)) continue
    t.area += r.areaM2 || 0
    if (r.exclusion) continue
    if (isTaikor(r.coat)) t.massKg += r.volume || 0
    else t.volumeM3 += r.volume || 0
  }
  return t
}

/** Строки трейса бэкенда, относящиеся к элементу (префикс «<id>: »). */
export function traceLinesFor(trace: string[] | undefined, id: string): string[] {
  if (!trace) return []
  const p = `${id}: `
  return trace.filter((l) => l.startsWith(p)).map((l) => l.slice(p.length))
}
