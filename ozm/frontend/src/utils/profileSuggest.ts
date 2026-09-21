import { CATEGORY_LABELS, handbookKey, type ProfileCategory } from './ocrImport'

/** Запись справочника масс (/ext/profiles) для подсказок при ручном вводе марки. */
export interface ProfileCatalogEntry {
  mark: string
  category?: string
  massPerMeter: number
}

/** Вариант в выпадающем списке: марка, вид профиля, масса 1 м. */
export interface ProfileOption {
  /** Марка как в справочнике («35Б2», «100Х100Х8», «140Х5»). */
  mark: string
  category: string
  categoryLabel: string
  massPerMeter: number
  /** Нормализованный ключ марки (handbookKey) — по нему идёт поиск. */
  key: string
}

export function buildProfileOptions(entries: ProfileCatalogEntry[]): ProfileOption[] {
  const out: ProfileOption[] = []
  const seen = new Set<string>()
  for (const e of entries || []) {
    const mark = String(e.mark || '').trim()
    if (!mark || !(e.massPerMeter > 0)) continue
    const category = String(e.category || '')
    const id = `${category}/${mark}`
    if (seen.has(id)) continue
    seen.add(id)
    out.push({
      mark,
      category,
      categoryLabel: CATEGORY_LABELS[category] || category,
      massPerMeter: e.massPerMeter,
      key: handbookKey(mark)
    })
  }
  return out
}

/**
 * Нормализация того, что печатает пользователь: регистр, латиница в букве
 * серии («35b2» → «35Б2»), знак умножения («100x8», «100*8» → «100Х8»),
 * запятая в дробной части. Ведущий значок типа профиля («□», «L», «I»)
 * снимается той же cleanMark, что и для марок из спецификации.
 */
export function normalizeQuery(query: string): string {
  return handbookKey(String(query || ''))
}

/**
 * Подходящие под набранный текст марки: сначала точное совпадение, затем те,
 * что начинаются с набранного, затем содержащие его. Внутри группы первыми
 * идут марки предпочтительного вида профиля (вид строки спецификации), потом
 * более короткие. Пустой запрос — пустой список.
 */
export function suggestProfiles(
  options: ProfileOption[],
  query: string,
  preferCategory: ProfileCategory | string = '',
  limit = 12
): ProfileOption[] {
  const q = normalizeQuery(query)
  if (!q) return []
  const scored: { o: ProfileOption; rank: number }[] = []
  for (const o of options) {
    let rank: number
    if (o.key === q) rank = 0
    else if (o.key.startsWith(q)) rank = 1
    else if (o.key.includes(q)) rank = 2
    else continue
    scored.push({ o, rank })
  }
  scored.sort((a, b) => {
    if (a.rank !== b.rank) return a.rank - b.rank
    const pa = preferCategory && a.o.category === preferCategory ? 0 : 1
    const pb = preferCategory && b.o.category === preferCategory ? 0 : 1
    if (pa !== pb) return pa - pb
    if (a.o.key.length !== b.o.key.length) return a.o.key.length - b.o.key.length
    if (a.o.key !== b.o.key) return a.o.key < b.o.key ? -1 : 1
    return a.o.categoryLabel < b.o.categoryLabel ? -1 : a.o.categoryLabel > b.o.categoryLabel ? 1 : 0
  })
  return scored.slice(0, limit).map((s) => s.o)
}

/** Точное совпадение набранной марки со справочником (для Enter без выбора из списка). */
export function exactProfile(
  options: ProfileOption[],
  query: string,
  preferCategory: ProfileCategory | string = ''
): ProfileOption | null {
  const q = normalizeQuery(query)
  if (!q) return null
  const hits = options.filter((o) => o.key === q)
  if (!hits.length) return null
  if (hits.length === 1) return hits[0]
  const preferred = preferCategory ? hits.find((o) => o.category === preferCategory) : undefined
  // марка есть в нескольких видах («140Х5» — квадратная и круглая труба):
  // без подсказки вида выбирать за пользователя нельзя
  return preferred || null
}
