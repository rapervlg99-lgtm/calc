import { describe, expect, it } from 'vitest'
import {
  autoGroupByConstruction,
  constructionGroupKey,
  constructionGroupTitle,
  hasConstructions,
  type AutoGroupLike
} from './autoGroup'

type G = AutoGroupLike & { fireLimit: string }
let seq = 1
const make = (name: string): G => ({ id: `a-${seq++}`, name, fireLimit: '', rowIds: [] })

const rows = [
  { id: 1, construction: 'Балки' },
  { id: 2, construction: 'Фермы' },
  { id: 3, construction: 'балки ' },
  { id: 4, construction: '' },
  { id: 5, construction: 'Колонны / Стойки' },
  { id: 6, construction: 'Колонны/Стойки' },
  { id: 7, construction: 'Фермы' }
]

describe('автогруппировка по элементу конструкции', () => {
  it('нормализует ключ и название', () => {
    expect(constructionGroupKey(' Колонны / Стойки ')).toBe('колонны/стойки')
    expect(constructionGroupKey('  балки   покрытия ')).toBe('балки покрытия')
    expect(constructionGroupTitle('балки  покрытия')).toBe('Балки покрытия')
    expect(constructionGroupTitle('Колонны / Стойки')).toBe('Колонны/Стойки')
    expect(constructionGroupTitle('')).toBe('')
    expect(hasConstructions([{ id: 1, construction: ' ' }])).toBe(false)
    expect(hasConstructions(rows)).toBe(true)
  })

  it('создаёт группы по названиям колонки в порядке появления', () => {
    const r = autoGroupByConstruction(rows, [] as G[], make)
    expect(r.groups.map((g) => g.name)).toEqual(['Балки', 'Фермы', 'Колонны/Стойки'])
    expect(r.groups.map((g) => g.rowIds)).toEqual([[1, 3], [2, 7], [5, 6]])
    expect(r.grouped).toBe(6)
    expect(r.skipped).toBe(1)
    expect(r.created).toBe(3)
    expect(new Set(r.touched)).toEqual(new Set(r.groups.map((g) => g.id)))
  })

  it('переиспользует существующую группу с тем же названием и сохраняет её атрибуты', () => {
    const manual: G = { id: 'm-1', name: 'фермы', fireLimit: 'R90', rowIds: [1] }
    const r = autoGroupByConstruction(rows, [manual], make)
    const fermy = r.groups.find((g) => g.id === 'm-1')!
    expect(fermy.name).toBe('фермы')            // название пользователя не переписываем
    expect(fermy.fireLimit).toBe('R90')
    expect(fermy.rowIds).toEqual([2, 7])          // балка №1 ушла в свою группу
    expect(r.groups[0].id).toBe('m-1')            // порядок существующих групп сохранён
    expect(r.created).toBe(2)
    expect(r.touched).toContain('m-1')
  })

  it('не трогает строки без элемента конструкции и удаляет опустевшие группы', () => {
    const g1: G = { id: 'm-1', name: 'Разное', fireLimit: '', rowIds: [1, 4] }
    const g2: G = { id: 'm-2', name: 'Пустая', fireLimit: '', rowIds: [] }
    const g3: G = { id: 'm-3', name: 'Старая', fireLimit: '', rowIds: [2] }
    const r = autoGroupByConstruction(rows, [g1, g2, g3], make)
    const names = r.groups.map((g) => g.name)
    expect(names).toContain('Разное')           // строка 4 без конструкции осталась в ней
    expect(names).toContain('Пустая')           // была пустой — остаётся
    expect(names).not.toContain('Старая')       // потеряла все строки — удалена
    expect(r.groups.find((g) => g.name === 'Разное')!.rowIds).toEqual([4])
    expect(r.touched).not.toContain('m-3')
    // исходные массивы не мутируются
    expect(g1.rowIds).toEqual([1, 4])
  })

  it('повторный запуск ничего не меняет', () => {
    const first = autoGroupByConstruction(rows, [] as G[], make)
    const second = autoGroupByConstruction(rows, first.groups, make)
    expect(second.groups).toEqual(first.groups)
    expect(second.created).toBe(0)
    expect(second.touched).toEqual([])
  })
})
