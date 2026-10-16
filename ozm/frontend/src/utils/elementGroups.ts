/**
 * Операции над группами элементов калькулятора (чистые функции, без Vue).
 *
 * Форма держит два списка: `ungrouped` — конструкции без группы (состояние по
 * умолчанию: одна конструкция, ни одной группы) и `groups` — группы, которые
 * пользователь создал сам. Группа не предсоздаётся: она появляется по кнопке
 * «Добавить группу конструкций», а её элементы пользователь туда переносит.
 * Механика та же, что в форме ОГЗ («Группа элементов»): назначить всем
 * элементам группы предел ОС и тип конструкции, удалить группу — её элементы
 * возвращаются в общий список.
 *
 * Элементы идентифицируются клиентским `_uid`, который не уходит в API.
 */

export interface GroupedElement {
  _uid?: number
  htLevel: number
  frType: string
}

export interface ElementGroupLike<E extends GroupedElement> {
  title: string
  elements: E[]
  /** Сколько раз повторяется вся группа (множитель длин и материалов); по умолчанию 1. */
  quantity?: number
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
 * Переносит элементы в группу `target` (в конец), сохраняя их порядок.
 * Элемент ищется и в списке «без группы», и в других группах: конструкция по
 * умолчанию живёт вне группы, и без первого поиска перенос в группу не находил
 * бы её вовсе. Возвращает число перенесённых; атрибуты группы применяются к ним.
 */
export function moveToGroup<E extends GroupedElement>(
  ungrouped: E[],
  groups: ElementGroupLike<E>[],
  uids: number[],
  target: number
): number {
  const dst = groups[target]
  if (!dst) return 0
  // элемент, уже стоящий в целевой группе, не переносим и не дублируем
  const inDst = new Set(dst.elements.map((e) => e._uid))
  const want = uids.filter((u) => !inDst.has(u))
  if (!want.length) return 0
  const moved = [...extractFromList(ungrouped, want), ...extractElements(groups, want)]
  dst.elements.push(...moved)
  applyGroupAttrs(dst, moved)
  return moved.length
}

/**
 * Обратный перенос: элементы с указанными uid уходят из своих групп в список
 * «без группы» (в конец, порядок сохраняется). Возвращает число перенесённых.
 */
export function moveToUngrouped<E extends GroupedElement>(
  ungrouped: E[],
  groups: ElementGroupLike<E>[],
  uids: number[]
): number {
  const moved = extractElements(groups, uids)
  ungrouped.push(...moved)
  return moved.length
}

/**
 * Перенос по номеру блока — то, что выбирает пользователь в списке на карточке
 * элемента: 0 — «без группы», 1…N — номер группы. Одна точка входа, чтобы
 * селектор и перетаскивание не разошлись в трактовке номера.
 */
export function moveToBlock<E extends GroupedElement>(
  ungrouped: E[],
  groups: ElementGroupLike<E>[],
  uids: number[],
  ordinal: number
): number {
  return ordinal === 0
    ? moveToUngrouped(ungrouped, groups, uids)
    : moveToGroup(ungrouped, groups, uids, ordinal - 1)
}

/** Вынимает элементы из плоского списка (порядок сохраняется). */
function extractFromList<E extends GroupedElement>(list: E[], uids: number[]): E[] {
  const want = new Set(uids)
  const moved: E[] = []
  for (let i = list.length - 1; i >= 0; i--) {
    const el = list[i]
    if (el._uid != null && want.has(el._uid)) {
      moved.unshift(el)
      list.splice(i, 1)
    }
  }
  return moved
}

/** Вынимает элементы из групп (порядок сохраняется), ничего не добавляя. */
function extractElements<E extends GroupedElement>(groups: ElementGroupLike<E>[], uids: number[]): E[] {
  const moved: E[] = []
  for (const g of groups) {
    moved.push(...extractFromList(g.elements, uids))
  }
  return moved
}

/**
 * Удаляет группу, переселяя её элементы в список «без группы»: группа — это
 * способ сгруппировать конструкции, а не место, где они обязаны жить.
 */
export function removeGroupKeepElements<E extends GroupedElement>(
  groups: ElementGroupLike<E>[],
  gi: number,
  ungrouped: E[] = []
): boolean {
  if (!groups[gi]) return false
  ungrouped.push(...groups[gi].elements)
  groups.splice(gi, 1)
  return true
}

/**
 * План запроса к API. Контракт требует хотя бы одну группу с quantity > 0 и
 * непустым списком элементов, поэтому конструкции без группы уходят первой
 * группой с пустым названием и количеством 1 — количество 1 ничего не домножает,
 * а название в расчёте и выгрузках не участвует. Пустые группы в запрос не
 * попадают.
 */
export function requestBlockPlan<E extends GroupedElement>(
  ungrouped: E[],
  groups: ElementGroupLike<E>[]
): { title: string; quantity: number; elements: E[] }[] {
  const plan: { title: string; quantity: number; elements: E[] }[] = []
  if (ungrouped.length) plan.push({ title: '', quantity: 1, elements: ungrouped })
  for (const g of groups) {
    if (!g.elements.length) continue
    plan.push({ title: g.title.trim(), quantity: Number(g.quantity) || 1, elements: g.elements })
  }
  return plan
}
