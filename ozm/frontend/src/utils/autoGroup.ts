/**
 * Автоматическая группировка строк формы ОГЗ по колонке «Элемент конструкции».
 *
 * Строки спецификации после OCR несут название колонки «Масса металла по
 * элементам конструкций», из которой взята масса: «Балки», «Фермы»,
 * «Колонны/Стойки», «Связи покрытия»… Кнопка «Автоматическая группировка»
 * раскладывает строки по группам с этими названиями — вместо того чтобы
 * создавать группы руками и перетаскивать позиции по одной.
 *
 * Правила:
 *  - группа ищется по названию без учёта регистра и лишних пробелов; если
 *    такая уже есть (в том числе созданная вручную), строки добавляются в неё,
 *    её предел ОС и тип конструкции сохраняются;
 *  - строки без элемента конструкции не трогаются: остаются там, где были;
 *  - группы, из которых ушли все строки, удаляются; пустые группы, которые
 *    были пустыми и до этого, остаются (пользователь мог только что их создать);
 *  - порядок существующих групп сохраняется, новые добавляются в порядке
 *    первого появления в списке строк.
 */

export interface AutoGroupRow {
  id: number
  construction: string
}

export interface AutoGroupLike {
  id: string
  name: string
  rowIds: number[]
}

export interface AutoGroupResult<G extends AutoGroupLike> {
  groups: G[]
  /** Строк распределено по группам (включая те, что уже стояли в нужной группе). */
  grouped: number
  /** Строк без элемента конструкции — оставлены как есть. */
  skipped: number
  /** Создано новых групп. */
  created: number
  /** id групп, состав которых изменился или которые созданы — для применения атрибутов. */
  touched: string[]
}

/** Ключ сравнения названий: без регистра, лишних пробелов и пробелов вокруг «/». */
export function constructionGroupKey(construction: string): string {
  return String(construction || '')
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/\s*\/\s*/g, '/')
    .toLowerCase()
}

/** Название группы из значения колонки: пробелы схлопнуты, первая буква заглавная. */
export function constructionGroupTitle(construction: string): string {
  const s = String(construction || '')
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/\s*\/\s*/g, '/')
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''
}

export function autoGroupByConstruction<G extends AutoGroupLike>(
  rows: AutoGroupRow[],
  groups: G[],
  makeGroup: (name: string) => G
): AutoGroupResult<G> {
  const out: G[] = groups.map((g) => ({ ...g, rowIds: [...g.rowIds] }))
  const hadRows = new Set(out.filter((g) => g.rowIds.length > 0).map((g) => g.id))
  const byKey = new Map<string, G>()
  for (const g of out) {
    const key = constructionGroupKey(g.name)
    if (key && !byKey.has(key)) byKey.set(key, g)
  }

  const touched = new Set<string>()
  let grouped = 0
  let skipped = 0
  let created = 0
  for (const row of rows) {
    const key = constructionGroupKey(row.construction)
    if (!key) {
      skipped++
      continue
    }
    let target = byKey.get(key)
    if (!target) {
      target = makeGroup(constructionGroupTitle(row.construction))
      out.push(target)
      byKey.set(key, target)
      created++
    }
    for (const g of out) {
      if (g === target) continue
      const before = g.rowIds.length
      g.rowIds = g.rowIds.filter((id) => id !== row.id)
      if (g.rowIds.length !== before) touched.add(g.id)
    }
    if (!target.rowIds.includes(row.id)) {
      target.rowIds.push(row.id)
      touched.add(target.id)
    }
    grouped++
  }

  const result = out.filter((g) => g.rowIds.length > 0 || !hadRows.has(g.id))
  const alive = new Set(result.map((g) => g.id))
  return {
    groups: result,
    grouped,
    skipped,
    created,
    touched: [...touched].filter((id) => alive.has(id))
  }
}

/** Есть ли что группировать: хотя бы одна строка с элементом конструкции. */
export function hasConstructions(rows: AutoGroupRow[]): boolean {
  return rows.some((r) => constructionGroupKey(r.construction) !== '')
}
