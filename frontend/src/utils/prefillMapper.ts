import type { ElementInput, HeatedSides, RollMark } from '../types/api'
import type { OgzRow, PrefillGroup, PrefillItem, PrefillPayload } from '../types/ogz'
import { elementDisplayName } from './constructionLabel'

export interface MappedElement {
  element: ElementInput
  /** true when profileMark did not match roll dict (manual pick needed). */
  profileMiss: boolean
  matchedLabel?: string
}

export interface PrefillMappedGroup {
  title: string
  elements: MappedElement[]
}

export interface PrefillMapped {
  elements: MappedElement[]
  /** Named groups from OCR form (or a single untitled bucket). */
  groups: PrefillMappedGroup[]
  /** True when at least one titled group came from the form table. */
  useGroups: boolean
  /**
   * Суммарная площадь листовой стали спецификации, м² — справочно. В расчёт
   * не идёт: это фасонки и накладки, а не бетонные конструкции (ОЗБ).
   */
  sheetAreaM2: number
}

/** Same inclusion rules as backend prefill.Build for profile rows. */
export function prefillableProfileRows(rows: OgzRow[]): OgzRow[] {
  return rows.filter(
    (r) =>
      !r.isSheet &&
      (r.status === 'Посчитано' || r.status === 'Требует проверки') &&
      r.lengthM > 0 &&
      r.fireLimit.trim() !== ''
  )
}

/** Attach rowIds + table groups so the calculator can rebuild named groups. */
export function enrichPrefillWithGroups(
  payload: PrefillPayload,
  profileRows: OgzRow[],
  tableGroups: PrefillGroup[] = []
): PrefillPayload {
  const included = prefillableProfileRows(profileRows)
  const items = (payload.items || []).map((it, i) => ({
    ...it,
    rowId: it.rowId ?? included[i]?.id
  }))
  const includedIds = new Set(included.map((r) => r.id))
  const groups = tableGroups
    .map((g) => ({
      title: (g.title || '').trim(),
      rowIds: (g.rowIds || []).filter((id) => includedIds.has(id))
    }))
    .filter((g) => g.rowIds.length > 0)

  return {
    ...payload,
    items,
    groups: groups.length ? groups : undefined
  }
}

const COAT_BY_LABEL: Record<string, string> = {
  'техно озм': '1',
  'taikor fp epoxy': '2',
  'taikor fp graphite': '3',
  'taikor fp extra + taikor fp graphite': '4',
  'акз': '1.5'
}

/** Strip assortment noise; unify latin/cyrillic lookalikes. */
export function normalizeMark(mark: string): string {
  let s = String(mark || '').trim().toUpperCase()
  // drop common prefixes from OCR / raw text
  s = s.replace(/^(ДВУТАВР|ДВУТАВР\.|I|ШВЕЛЛЕР|ШВ\.?|УГОЛОК|УГ\.?|ТРУБА|ТР\.?|ТР\s+|PIPE)\s*/i, '')
  s = s
    .replace(/[×ХX]/gi, 'X')
    .replace(/[БB]/gi, 'B') // beam series letter
    .replace(/[КK]/gi, 'K')
    .replace(/[УY]/gi, 'Y') // sometimes У vs Y
    .replace(/[''`′]/g, '')
    .replace(/[^\w\u0400-\u04FF.XBK]/gi, '') // drop spaces/punct except mark chars
    .replace(/\s+/g, '')
  // After latinizing B, Cyrillic Б already mapped; collapse leftover spaces
  return s.replace(/\s+/g, '')
}

export function markAliases(mark: string): string[] {
  const base = normalizeMark(mark)
  const raw = String(mark || '').trim().toUpperCase().replace(/\s+/g, '')
  const set = new Set<string>([base, raw, normalizeMark(raw)])
  // with/without leading I
  if (base.startsWith('I') && base.length > 1) set.add(base.slice(1))
  else set.add('I' + base)
  // spaced series: 40B1 <-> 40 B1 already collapsed; also 40Б1 variants
  const m = base.match(/^(\d+)([A-Z]+)(\d*)$/)
  if (m) {
    set.add(`${m[1]}${m[2]}${m[3]}`)
    set.add(`${m[1]} ${m[2]}${m[3]}`.replace(/\s+/g, ''))
  }
  // «140х90х8» в спецификации — это «140/90 x 8» в справочнике неравнополочных
  // уголков и гнутых профилей; «63х63х5» — «63 x 5» равнополочного.
  const trip = raw.match(/^(\d+(?:[.,]\d+)?)[XХ×*](\d+(?:[.,]\d+)?)[XХ×*](\d+(?:[.,]\d+)?)$/i)
  if (trip) {
    set.add(normalizeMark(trip[1] === trip[2] ? `${trip[1]}X${trip[3]}` : `${trip[1]}/${trip[2]}X${trip[3]}`))
  }
  return [...set].filter(Boolean)
}

export function mapFireLimit(fireLimit: string): number {
  const m = String(fireLimit || '').trim().match(/R?\s*(\d+)/i)
  return m ? Number(m[1]) : 15
}

export function mapBearingType(bearingType: string): string {
  const s = String(bearingType || '').trim().toLowerCase()
  if (s.includes('самонес')) return '0'
  if (s.includes('несущ')) return '1'
  return '1'
}

export function mapCoatingType(coatingType: string): string {
  const key = String(coatingType || '').trim().toLowerCase()
  if (!key) return '1'
  if (COAT_BY_LABEL[key]) return COAT_BY_LABEL[key]
  for (const [label, value] of Object.entries(COAT_BY_LABEL)) {
    if (key.includes(label) || label.includes(key)) return value
  }
  return '1'
}

export function mapHeatingSides(heatingSides: string): HeatedSides {
  const raw = String(heatingSides || '').trim().toLowerCase()
  if (!raw || raw === '4' || raw === 'все' || raw === 'со всех сторон') {
    return { left: true, top: true, right: true, bottom: true }
  }
  const sides: HeatedSides = { left: false, top: false, right: false, bottom: false }
  if (/лев|left/.test(raw)) sides.left = true
  if (/прав|right/.test(raw)) sides.right = true
  if (/верх|top|сверху/.test(raw)) sides.top = true
  if (/низ|bottom|снизу/.test(raw)) sides.bottom = true
  if (!sides.left && !sides.top && !sides.right && !sides.bottom) {
    return { left: true, top: true, right: true, bottom: true }
  }
  return sides
}

/** Build index once per dicts load for O(1) exact lookup. */
export function buildRollIndex(roll: RollMark[]): Map<string, RollMark> {
  const idx = new Map<string, RollMark>()
  for (const r of roll) {
    if (!r.label && !r.id) continue
    for (const a of markAliases(r.label || r.id)) {
      if (!idx.has(a)) idx.set(a, r)
    }
    for (const a of markAliases(r.id)) {
      if (!idx.has(a)) idx.set(a, r)
    }
  }
  return idx
}

/** Match profileMark to roll entry (exact aliases, then soft contains). */
export function matchRoll(profileMark: string, roll: RollMark[], index?: Map<string, RollMark>): RollMark | null {
  const aliases = markAliases(profileMark)
  const idx = index || buildRollIndex(roll)
  for (const a of aliases) {
    const hit = idx.get(a)
    if (hit) return hit
  }
  // soft: alias contained in label or vice versa (short marks only).
  // Марки, начинающиеся с цифр, по подстроке не сравниваем: «130К1» содержит
  // «30К1», «140х5» содержит «40х5» — это разные профили, а не варианты записи.
  const withLabel = roll.filter((r) => r.label || r.id)
  for (const a of aliases) {
    if (a.length < 2) continue
    const soft = withLabel.find((r) => {
      const lab = normalizeMark(r.label || r.id)
      if (lab === a) return true
      // алиасы вида «I40B1» — тот же номер с префиксом двутавра
      const numLed = (m: string) => /^\d/.test(m.replace(/^I(?=\d)/, ''))
      if (numLed(lab) && numLed(a)) return false
      return lab.includes(a) || a.includes(lab)
    })
    if (soft) return soft
  }
  return null
}

export function mapPrefillItem(
  item: PrefillItem,
  roll: RollMark[] = [],
  index?: Map<string, RollMark>
): MappedElement {
  // Подсказка о формах сечения сужает поиск: «140х5» без неё находит первую
  // попавшуюся трубу (круглую), а строка спецификации была квадратной.
  const shapes = item.shapes && item.shapes.length ? item.shapes : null
  const pool = shapes ? roll.filter((r) => shapes.includes(r.shape)) : roll
  const hit = matchRoll(item.profileMark, pool, shapes ? buildRollIndex(pool) : index)
  const coat = mapCoatingType(item.coatingType)
  const mark = item.profileMark || hit?.label || ''
  const construction = item.construction || ''
  // Вид профиля — из наименования группы спецификации («Швеллеры стальные…» →
  // швеллер), даже если марка не нашлась в справочнике проката: первая форма
  // подсказки — базовая форма семейства.
  const familyShape = shapes ? shapes[0] : undefined
  const element: ElementInput = {
    title: elementDisplayName(construction, mark),
    construction,
    shape: hit?.shape || familyShape || 'I-beam_',
    rollId: hit?.id || undefined,
    dims: hit?.dims ? { ...hit.dims } : { h: 100, b: 55, s: 4.1, t: 5.7, R: 7 },
    frType: mapBearingType(item.bearingType),
    htLevel: mapFireLimit(item.fireLimit),
    sides: mapHeatingSides(item.heatingSides),
    lengthM: Number(item.lengthM) || 1,
    quantity: 1,
    coat,
    method: coat === '1' ? '1' : '0',
    primer: false,
    enamel: false,
    decor: true
  }
  return {
    element,
    profileMiss: !hit,
    matchedLabel: hit?.label
  }
}

export function mapPrefillPayload(payload: PrefillPayload, roll: RollMark[] = []): PrefillMapped {
  const index = buildRollIndex(roll)
  const items = payload.items || []
  const mapped = items.map((it) => mapPrefillItem(it, roll, index))
  const sheetAreaM2 = Number(payload.sheet?.areaM2) > 0 ? Number(payload.sheet.areaM2) : 0

  const tableGroups = (payload.groups || []).filter((g) => g.rowIds?.length)
  if (!tableGroups.length) {
    return {
      elements: mapped,
      groups: [{ title: '', elements: mapped }],
      useGroups: false,
      sheetAreaM2
    }
  }

  const byRowId = new Map<number, MappedElement>()
  items.forEach((it, i) => {
    if (it.rowId != null && mapped[i]) byRowId.set(it.rowId, mapped[i])
  })

  const used = new Set<number>()
  const groups: PrefillMappedGroup[] = []
  for (const g of tableGroups) {
    const els: MappedElement[] = []
    for (const rid of g.rowIds) {
      const m = byRowId.get(rid)
      if (!m || used.has(rid)) continue
      els.push(m)
      used.add(rid)
    }
    if (els.length) {
      groups.push({ title: (g.title || '').trim(), elements: els })
    }
  }

  const ungrouped = mapped.filter((_, i) => {
    const rid = items[i]?.rowId
    return rid == null || !used.has(rid)
  })
  if (ungrouped.length) {
    groups.push({ title: '', elements: ungrouped })
  }

  if (!groups.length) {
    return {
      elements: mapped,
      groups: [{ title: '', elements: mapped }],
      useGroups: false,
      sheetAreaM2
    }
  }

  return {
    elements: groups.flatMap((g) => g.elements),
    groups,
    useGroups: groups.some((g) => !!g.title),
    sheetAreaM2
  }
}
