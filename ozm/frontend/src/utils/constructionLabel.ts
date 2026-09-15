/** Human-readable construction label for UI (table + element titles). */
export function constructionLabel(construction: string): string {
  const c = String(construction || '').trim()
  if (!c) return ''
  const map: Record<string, string> = {
    'Колонны/Стойки': 'колонна / стойка',
    Балки: 'балка',
    Связи: 'связь',
    Прогоны: 'прогон',
    Ригели: 'ригели'
  }
  return map[c] ?? c.toLowerCase()
}

/** Element title from construction + profile mark, e.g. "балка 40Б1". */
export function elementDisplayName(
  construction: string,
  mark: string,
  fallback = 'Элемент'
): string {
  const c = constructionLabel(construction)
  const m = String(mark || '').trim()
  if (c && m) return `${c} ${m}`
  return m || c || fallback
}
