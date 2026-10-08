import { describe, expect, it } from 'vitest'
import { sourceRollsForGost, standardNumber } from './rollCatalog'

/**
 * Правило редакций (согласовано 07.10): если лист ссылается на редакцию, которой
 * в сортаменте нет («ГОСТ 30245-2012» против 30245-2003, «ГОСТ 8240-97» против
 * 8240-2026), масса берётся из своей редакции того же номера стандарта, а строка
 * помечается как требующая проверки — редакция не совпала.
 */
const roll = [
  { id: '1', label: '50Ш4', shape: 'I-beam_sm', standard: 'ГОСТ 35087-2024', massPerMeter: 173.7833 },
  { id: '2', label: '50Ш4', shape: 'I-beam_sm', standard: 'СТО АСЧМ 20-93', massPerMeter: 173.8 },
  { id: '3', label: '250x6', shape: 'tube_sq', standard: 'ГОСТ 30245-2003', massPerMeter: 45.24 },
  { id: '4', label: '22П', shape: 'channel_', standard: 'ГОСТ 8240-2026', massPerMeter: 20.9595 },
  { id: '5', label: '22П', shape: 'channel_', standard: 'ГОСТ 8240-97', massPerMeter: 21.0 },
] as never[]

describe('подбор массы по стандарту листа (правило редакций)', () => {
  it('точная редакция имеет приоритет', () => {
    expect(sourceRollsForGost(roll, 'ГОСТ 8240-97').map((r) => r.massPerMeter)).toEqual([21])
  })

  it('стандарт «СТО АСЧМ 20-93» находит свои записи', () => {
    expect(sourceRollsForGost(roll, 'СТО АСЧМ 20-93').map((r) => r.massPerMeter)).toEqual([173.8])
  })

  it('редакция того же стандарта используется, когда точной нет', () => {
    expect(sourceRollsForGost(roll, 'ГОСТ 30245-2012').map((r) => r.massPerMeter)).toEqual([45.24])
    expect(sourceRollsForGost(roll, 'ГОСТ 8240-89').map((r) => r.massPerMeter)).toEqual([20.9595, 21])
  })

  it('чужой стандарт не подставляется', () => {
    expect(sourceRollsForGost(roll, 'ГОСТ 27772-2021')).toEqual([])
  })

  it('номер стандарта считается без года', () => {
    expect(standardNumber('ГОСТ 30245-2012')).toBe('30245')
    expect(standardNumber('СТО АСЧМ 20-93')).toBe('20')
    expect(standardNumber('ГОСТ Р 57837-2017')).toBe('57837')
  })
})
