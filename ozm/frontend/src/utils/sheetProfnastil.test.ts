import { describe, expect, it } from 'vitest'
import { isSheetRow, sheetMassPerM2, sheetThicknessMm } from './ocrImport'

/**
 * Профнастил (решение Олега 07.10): интересует только толщина, она стоит
 * последним числом в обозначении — «Н57х750х0,8» → 0,8 мм → 6,28 кг/м².
 * Раньше такие строки уходили в ручной ввод с массой 0.
 */
describe('профнастил: толщина из обозначения', () => {
  it('берёт последнее число как толщину', () => {
    expect(sheetThicknessMm('Н57х750х0,8')).toBe(0.8)
    expect(sheetThicknessMm('Н57-750-0.8')).toBe(0.8)
    expect(sheetThicknessMm('Н57х750х0,9')).toBe(0.9)
    expect(sheetThicknessMm('С21-1000-0,7')).toBe(0.7)
  })

  it('прежние обозначения листа не сломались', () => {
    expect(sheetThicknessMm('δ=4')).toBe(4)
    expect(sheetThicknessMm('t8')).toBe(8)
    expect(sheetThicknessMm('10 мм')).toBe(10)
  })

  it('масса листа считается по толщине', () => {
    expect(sheetMassPerM2(0.8)).toBeCloseTo(6.28, 2)
  })

  it('строка профнастила распознаётся как листовая', () => {
    expect(isSheetRow({ profile_group: 'Профнастил по ГОСТ 24045-94', profile_size: 'Н57х750х0.8' })).toBe(true)
    expect(isSheetRow({ profile_group: 'Трубы стальные квадратные', profile_size: '250х6' })).toBe(false)
  })
})
