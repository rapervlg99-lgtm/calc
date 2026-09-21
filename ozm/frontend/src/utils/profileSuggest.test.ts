import { describe, expect, it } from 'vitest'
import { buildProfileOptions, exactProfile, normalizeQuery, suggestProfiles } from './profileSuggest'

const catalog = buildProfileOptions([
  { mark: '35Б1', category: 'balka', massPerMeter: 38.9 },
  { mark: '35Б2', category: 'balka', massPerMeter: 43.3 },
  { mark: '35Ш1', category: 'balka', massPerMeter: 65.3 },
  { mark: '135Б1', category: 'balka', massPerMeter: 0 },          // масса 0 — не подсказка
  { mark: '100Х100Х8', category: 'ygolok', massPerMeter: 12.25 },
  { mark: '100Х8', category: 'tryba_es_kvadr', massPerMeter: 21.4 },
  { mark: '140Х5', category: 'tryba_es_kvadr', massPerMeter: 20.9 },
  { mark: '140Х5', category: 'tryba_es_krug', massPerMeter: 16.6 },
  { mark: '140Х5', category: 'tryba_es_krug', massPerMeter: 16.6 }, // дубль
  { mark: '16П', category: 'shveller', massPerMeter: 14.2 },
  { mark: '16', category: 'shveller', massPerMeter: 14.2 }
])

describe('profileSuggest', () => {
  it('нормализует ввод пользователя как марку справочника', () => {
    expect(normalizeQuery('35b2')).toBe('35Б2')
    expect(normalizeQuery(' 100x8 ')).toBe('100Х8')
    expect(normalizeQuery('100*100*8')).toBe('100Х100Х8')
    expect(normalizeQuery('□ 140х5')).toBe('140Х5')
    expect(normalizeQuery('')).toBe('')
  })

  it('строит варианты без дублей и без записей с нулевой массой', () => {
    expect(catalog.map((o) => `${o.category}/${o.mark}`)).not.toContain('balka/135Б1')
    expect(catalog.filter((o) => o.mark === '140Х5')).toHaveLength(2)
    expect(catalog.find((o) => o.mark === '35Б2')?.categoryLabel).toBe('Двутавр')
  })

  it('по префиксу: точное совпадение, потом начинающиеся с набранного, потом содержащие', () => {
    const marks = suggestProfiles(catalog, '35б').map((o) => o.mark)
    expect(marks).toEqual(['35Б1', '35Б2'])
    const one = suggestProfiles(catalog, '35Б1').map((o) => o.mark)
    expect(one[0]).toBe('35Б1')
    // «0Х8» встречается внутри «100Х8» и «100Х100Х8»
    expect(suggestProfiles(catalog, '0x8').map((o) => o.mark)).toEqual(['100Х8', '100Х100Х8'])
    expect(suggestProfiles(catalog, '')).toEqual([])
    expect(suggestProfiles(catalog, 'zzz')).toEqual([])
  })

  it('предпочитает вид профиля строки, когда марка есть в нескольких видах', () => {
    const round = suggestProfiles(catalog, '140х5', 'tryba_es_krug')
    expect(round.map((o) => o.category)).toEqual(['tryba_es_krug', 'tryba_es_kvadr'])
    const square = suggestProfiles(catalog, '140х5', 'tryba_es_kvadr')
    expect(square.map((o) => o.category)).toEqual(['tryba_es_kvadr', 'tryba_es_krug'])
  })

  it('ограничивает длину списка', () => {
    expect(suggestProfiles(catalog, '1', '', 3)).toHaveLength(3)
  })

  it('точное совпадение для Enter: однозначная марка или марка вида строки', () => {
    expect(exactProfile(catalog, '35b2')?.massPerMeter).toBe(43.3)
    expect(exactProfile(catalog, '140x5')).toBeNull()                       // две категории, вид неизвестен
    expect(exactProfile(catalog, '140x5', 'tryba_es_krug')?.massPerMeter).toBe(16.6)
    expect(exactProfile(catalog, '35Б')).toBeNull()
  })
})
