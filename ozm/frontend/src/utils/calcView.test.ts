import { describe, expect, it } from 'vitest'
import { isAkz, resultDelta, resultOutput, totalsOf } from './calcView'
import type { ElementResult } from '../types/api'

/** Строка результата с осмысленными значениями по умолчанию. */
function row(over: Partial<ElementResult> = {}): ElementResult {
  return {
    id: 'e1', groupId: 'g1', title: '', shape: 'I-beam_sm', f: 0, pi: 0, dpr: 0, delta: 0,
    lining: 0, areaM2: 0, volume: 0, coat: '1', htLevel: 60, lengthM: 1, quantity: 1,
    ...over
  }
}

describe('показ результатов расчёта', () => {
  it('конструкция только с АКЗ входит в расчёт, но не в итог огнезащиты', () => {
    // Площадь АКЗ — это площадь антикоррозионной окраски, а не огнезащиты,
    // и огнезащитного материала у такой конструкции нет.
    const t = totalsOf([
      row({ id: 'e1', coat: '1.5', areaM2: 12, volume: 0, htLevel: 0 }),
      row({ id: 'e2', coat: '1', areaM2: 10, volume: 0.5 }),
      row({ id: 'e3', coat: '2', areaM2: 4, volume: 33 })
    ])
    expect(t.area).toBe(14)
    expect(t.volumeM3).toBe(0.5)
    expect(t.massKg).toBe(33)
    expect(t.exclusions).toBe(0)
  })

  it('исключённые строки считаются отдельно и в объём не идут', () => {
    const t = totalsOf([
      row({ id: 'e1', coat: '1', areaM2: 10, volume: 0.5 }),
      row({ id: 'e2', coat: '1', areaM2: 6, volume: 0, exclusion: 'недостижимый предел' })
    ])
    expect(t.exclusions).toBe(1)
    expect(t.area).toBe(16)
    expect(t.volumeM3).toBe(0.5)
  })

  it('у АКЗ нет ни толщины огнезащиты, ни расхода — только площадь', () => {
    const akz = row({ coat: '1.5', htLevel: 0, areaM2: 12 })
    expect(isAkz(akz.coat)).toBe(true)
    expect(resultDelta(akz)).toBe('—')
    expect(resultOutput(akz)).toBe('—')
  })

  it('огнезащита без заданного R показывает сообщение, а не нулевую толщину', () => {
    const noR = row({ coat: '1', htLevel: 0, exclusion: 'не задан предел огнестойкости R — укажите его для огнезащитного покрытия' })
    expect(resultDelta(noR)).toBe('—')
    expect(resultOutput(noR)).toBe('не достигается')
    expect(totalsOf([noR]).exclusions).toBe(1)
  })
})
