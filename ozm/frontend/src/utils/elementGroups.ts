/**
 * Операции над группами элементов калькулятора (чистые функции, без Vue).
 *
 * Группы — это `form.groups`: массив `{ title, elements }`. Элементы
 * идентифицируются клиентским `_uid`, который не уходит в API. Механика та же,
 * что в форме ОГЗ («Группа элементов»): создать группу, затянуть в неё позиции
 * из общего списка, назначить всем элементам группы предел ОС и тип
 * конструкции, удалить группу — её элементы возвращаются в общий список.
 */

export interface GroupedElement {
  _uid?: number
  htLevel: number
  frType: string
}

export interface ElementGroupLike<E extends GroupedElement> {
  title: string
  elements: E[]
  /** Общий предел ОС группы (R); '' — не задан. */
  groupHt?: number | ''
  /** Общий тип конструкции группы ('1' несущая / '0' самонесущая); '' — не задан. */
  groupFr?: string
}

let uidSeq = 1

export function nextUid(): number {
  return uidSeq++
}

export function uidOf<E extends GroupedElement>(el: E): number {
  if (el._uid == null) el._uid = nextUid()
  return el._uid
}

export function findElement<E extends GroupedElement>(
  groups: ElementGroupLike<E>[],
  uid: number
): { gi: number; ei: number } | null {
  for (let gi = 0; gi < groups.length; gi++) {
    const ei = groups[gi].elements.findIndex((e) => e._uid === uid)
    if (ei !== -1) return { gi, ei }
  }
  return null
}

/** Имя для новой группы: «Группа N», не совпадающее с существующими. */
export function nextGroupTitle<E extends GroupedElement>(groups: ElementGroupLike<E>[]): string {
  const used = new Set(groups.map((g) => g.title.trim()))
  let n = groups.length + 1
  while (used.has(`Группа ${n}`)) n++
  return `Группа ${n}`
}

/** Применяет групповые атрибуты (R, тип конструкции) к элементам группы. */
export function applyGroupAttrs<E extends GroupedElement>(group: ElementGroupLike<E>, els?: E[]): void {
  const targets = els ?? group.elements
  for (const el of targets) {
    if (group.groupHt !== undefined && group.groupHt !== '') el.htLevel = Number(group.groupHt)
    if (group.groupFr) el.frType = group.groupFr
  }
}

/**
 * Переносит элементы с указанными uid в группу `target` (в конец), сохраняя их
 * порядок. Возвращает число перенесённых. Атрибуты группы применяются к
 * перенесённым элементам.
 */
export function moveToGroup<E extends GroupedElement>(
  groups: ElementGroupLike<E>[],
  uids: number[],
  target: number
): number {
  const dst = groups[target]
  if (!dst) return 0
  const want = new Set(uids)
  const moved: E[] = []
  for (let gi = 0; gi < groups.length; gi++) {
    const g = groups[gi]
    if (gi === target) continue
    // внутри группы идём с конца (чтобы splice не сдвигал индексы), но
    // собираем в исходном порядке; группы обходим по возрастанию
    const part: E[] = []
    for (let ei = g.elements.length - 1; ei >= 0; ei--) {
      const el = g.elements[ei]
      if (el._uid != null && want.has(el._uid)) {
        part.unshift(el)
        g.elements.splice(ei, 1)
      }
    }
    moved.push(...part)
  }
  dst.elements.push(...moved)
  applyGroupAttrs(dst, moved)
  return moved.length
}

/**
 * Удаляет группу, переселяя её элементы в соседнюю (предыдущую, иначе
 * следующую). Последнюю группу удалить нельзя — элементы должны где-то жить.
 */
export function removeGroupKeepElements<E extends GroupedElement>(
  groups: ElementGroupLike<E>[],
  gi: number
): boolean {
  if (groups.length <= 1 || !groups[gi]) return false
  const receiver = gi > 0 ? groups[gi - 1] : groups[gi + 1]
  receiver.elements.push(...groups[gi].elements)
  groups.splice(gi, 1)
  return true
}
