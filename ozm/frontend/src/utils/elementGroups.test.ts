import { describe, expect, it } from 'vitest'
import {
  applyGroupAttrs,
  findElement,
  moveToGroup,
  nextGroupTitle,
  removeGroupKeepElements,
  uidOf,
  type ElementGroupLike
} from './elementGroups'

type E = { _uid?: number; name: string; htLevel: number; frType: string }
const el = (name: string, uid: number): E => ({ _uid: uid, name, htLevel: 15, frType: '1' })

function fixture(): ElementGroupLike<E>[] {
  return [
    { title: 'Группа 1', elements: [el('a', 1), el('b', 2), el('c', 3)] },
    { title: 'Группа 2', elements: [el('d', 4)] }
  ]
}

describe('element groups', () => {
  it('assigns uids lazily and finds elements', () => {
    const groups = fixture()
    const fresh: E = { name: 'z', htLevel: 15, frType: '1' }
    expect(uidOf(fresh)).toBeGreaterThan(0)
    expect(uidOf(fresh)).toBe(fresh._uid)
    expect(findElement(groups, 4)).toEqual({ gi: 1, ei: 0 })
    expect(findElement(groups, 99)).toBeNull()
  })

  it('moves selected elements into a group keeping order', () => {
    const groups = fixture()
    expect(moveToGroup(groups, [1, 3], 1)).toBe(2)
    expect(groups[0].elements.map((e) => e.name)).toEqual(['b'])
    expect(groups[1].elements.map((e) => e.name)).toEqual(['d', 'a', 'c'])
    // элемент, уже находящийся в целевой группе, не дублируется
    expect(moveToGroup(groups, [4], 1)).toBe(0)
    expect(groups[1].elements).toHaveLength(3)
    // несуществующая группа
    expect(moveToGroup(groups, [2], 5)).toBe(0)
  })

  it('applies group attributes to moved elements and to the whole group', () => {
    const groups = fixture()
    groups[1].groupHt = 90
    groups[1].groupFr = '0'
    moveToGroup(groups, [1], 1)
    const a = groups[1].elements.find((e) => e.name === 'a')!
    expect(a.htLevel).toBe(90)
    expect(a.frType).toBe('0')
    // d ещё не тронут — атрибуты применяются явно
    expect(groups[1].elements[0].htLevel).toBe(15)
    applyGroupAttrs(groups[1])
    expect(groups[1].elements.every((e) => e.htLevel === 90 && e.frType === '0')).toBe(true)
    // пустой R не трогает элементы
    groups[0].groupHt = ''
    applyGroupAttrs(groups[0])
    expect(groups[0].elements.every((e) => e.htLevel === 15)).toBe(true)
  })

  it('removes a group but keeps its elements', () => {
    const groups = fixture()
    expect(removeGroupKeepElements(groups, 1)).toBe(true)
    expect(groups).toHaveLength(1)
    expect(groups[0].elements.map((e) => e.name)).toEqual(['a', 'b', 'c', 'd'])
    expect(removeGroupKeepElements(groups, 0)).toBe(false) // последнюю не удаляем
    const g2 = fixture()
    expect(removeGroupKeepElements(g2, 0)).toBe(true) // первая — элементы уходят в следующую
    expect(g2[0].elements.map((e) => e.name)).toEqual(['d', 'a', 'b', 'c'])
  })

  it('names new groups without collisions', () => {
    expect(nextGroupTitle(fixture())).toBe('Группа 3')
    expect(nextGroupTitle([{ title: 'Группа 2', elements: [] }])).toBe('Группа 3')
    expect(nextGroupTitle([])).toBe('Группа 1')
  })
})
