import { describe, expect, it } from 'vitest'
import {
  buildRollIndex,
  enrichPrefillWithGroups,
  mapBearingType,
  mapCoatingType,
  mapFireLimit,
  mapHeatingSides,
  mapPrefillItem,
  mapPrefillPayload,
  matchRoll,
  normalizeMark,
  prefillableProfileRows
} from './prefillMapper'
import type { OgzRow, PrefillPayload } from '../types/ogz'
import type { RollMark } from '../types/api'

const sampleRoll: RollMark[] = [
  { id: '79', shape: 'I-beam_sm', label: '10 Б1', dims: { h: 100, b: 55, s: 4.1, t: 5.7, R: 7 } },
  { id: '100001', shape: 'I-beam_sm', label: '26 Б1', dims: { h: 258, b: 120, s: 5.8, t: 8.5, R: 12 } },
  { id: '46', shape: 'I-beam_sm', label: '40 Б1', dims: { h: 396, b: 199, s: 7, t: 11, R: 16 } },
  { id: '226', shape: 'I-beam_sm', label: '25 Б1', dims: { h: 248, b: 124, s: 5, t: 8, R: 12 } },
  { id: '778', shape: 'I-beam_sm', label: '35 Б2', dims: { h: 350, b: 175, s: 7, t: 11, R: 14 } }
]

function row(partial: Partial<OgzRow> & Pick<OgzRow, 'id' | 'profileMark'>): OgzRow {
  return {
    name: '',
    profileRaw: '',
    gostProfile: '',
    steelGrade: '',
    ppNumber: '',
    construction: '',
    mass: 0,
    massUnit: 'kg',
    massPerMeter: 0,
    massSource: '',
    sourceUrl: '',
    isSheet: false,
    lengthM: 10,
    areaM2: 0,
    classification: '',
    status: 'Посчитано',
    heatingSides: '4',
    fireLimit: 'R60',
    bearingType: 'Несущая',
    coatingType: 'ТЕХНО ОЗМ',
    ...partial
  }
}

describe('prefillMapper', () => {
  it('normalizes marks', () => {
    expect(normalizeMark('40 Б1')).toBe('40B1')
    expect(normalizeMark('40Б1')).toBe('40B1')
    expect(normalizeMark('I40Б1')).toBe('40B1')
    expect(normalizeMark('160х5')).toBe('160X5')
  })

  it('maps R60 fire limit', () => {
    expect(mapFireLimit('R60')).toBe(60)
    expect(mapFireLimit('r120')).toBe(120)
    expect(mapFireLimit('45')).toBe(45)
  })

  it('maps bearing type', () => {
    expect(mapBearingType('Несущая')).toBe('1')
    expect(mapBearingType('Самонесущая')).toBe('0')
  })

  it('maps coating labels', () => {
    expect(mapCoatingType('ТЕХНО ОЗМ')).toBe('1')
    expect(mapCoatingType('TAIKOR FP Graphite')).toBe('3')
    expect(mapCoatingType('АКЗ')).toBe('1.5')
    expect(mapCoatingType('TAIKOR FP Extra + TAIKOR FP Graphite')).toBe('4')
  })

  it('maps heating sides', () => {
    expect(mapHeatingSides('4')).toEqual({ left: true, top: true, right: true, bottom: true })
    expect(mapHeatingSides('снизу, слева, справа')).toEqual({
      left: true,
      top: false,
      right: true,
      bottom: true
    })
  })

  it('matches roll by OCR-like marks', () => {
    const idx = buildRollIndex(sampleRoll)
    expect(matchRoll('10Б1', sampleRoll, idx)?.label).toBe('10 Б1')
    expect(matchRoll('10 Б1', sampleRoll, idx)?.shape).toBe('I-beam_sm')
    expect(matchRoll('10B1', sampleRoll, idx)?.dims.h).toBe(100)
    expect(matchRoll('26Б1', sampleRoll, idx)?.dims.h).toBe(258)
    expect(matchRoll('26 Б1', sampleRoll, idx)?.label).toBe('26 Б1')
    expect(matchRoll('40Б1', sampleRoll, idx)?.id).toBe('46')
    expect(matchRoll('40 Б1', sampleRoll, idx)?.label).toBe('40 Б1')
    expect(matchRoll('I40Б1', sampleRoll, idx)?.shape).toBe('I-beam_sm')
    expect(matchRoll('25Б1', sampleRoll, idx)?.dims.h).toBe(248)
    expect(matchRoll('99ZZ', sampleRoll, idx)).toBeNull()
  })

  it('maps item with hit and miss', () => {
    const hit = mapPrefillItem({
      profileMark: '40Б1',
      construction: 'Балки',
      lengthM: 14.8,
      heatingSides: '4',
      fireLimit: 'R90',
      bearingType: 'Несущая',
      coatingType: 'TAIKOR FP Graphite'
    }, sampleRoll)
    expect(hit.profileMiss).toBe(false)
    expect(hit.element.rollId).toBe('46')
    expect(hit.element.shape).toBe('I-beam_sm')
    expect(hit.element.dims?.h).toBe(396)
    expect(hit.element.htLevel).toBe(90)
    expect(hit.element.coat).toBe('3')
    expect(hit.element.title).toBe('балка 40Б1')
    expect(hit.element.construction).toBe('Балки')

    const miss = mapPrefillItem({
      profileMark: 'ZZ-99',
      lengthM: 1,
      heatingSides: '4',
      fireLimit: 'R60',
      bearingType: 'Несущая',
      coatingType: 'ТЕХНО ОЗМ'
    }, sampleRoll)
    expect(miss.profileMiss).toBe(true)
    expect(miss.element.title).toBe('ZZ-99')
  })

  it('maps payload items', () => {
    const payload: PrefillPayload = {
      version: '1',
      jobId: 'demo',
      items: [
        {
          profileMark: '26Б1',
          lengthM: 11.2,
          heatingSides: 'снизу, слева, справа',
          fireLimit: 'R60',
          bearingType: 'Несущая',
          coatingType: 'ТЕХНО ОЗМ'
        }
      ],
      sheet: { areaM2: 24.6 }
    }
    const mapped = mapPrefillPayload(payload, sampleRoll)
    expect(mapped.elements).toHaveLength(1)
    expect(mapped.elements[0].profileMiss).toBe(false)
    expect(mapped.elements[0].element.htLevel).toBe(60)
    expect(mapped.elements[0].element.coat).toBe('1')
    expect(mapped.elements[0].element.method).toBe('1')
    expect(mapped.sheetAreaM2).toBe(24.6)
    expect(mapped.useGroups).toBe(false)
    expect(mapped.groups).toHaveLength(1)
  })

  it('enriches prefill with table group names', () => {
    const rows = [
      row({ id: 1, profileMark: '26Б1' }),
      row({ id: 2, profileMark: '40Б1' }),
      row({ id: 3, profileMark: '10Б1', fireLimit: '' })
    ]
    expect(prefillableProfileRows(rows).map((r) => r.id)).toEqual([1, 2])

    const payload: PrefillPayload = {
      version: '1',
      jobId: 'demo',
      items: [
        {
          profileMark: '26Б1',
          lengthM: 11.2,
          heatingSides: '4',
          fireLimit: 'R60',
          bearingType: 'Несущая',
          coatingType: 'ТЕХНО ОЗМ'
        },
        {
          profileMark: '40Б1',
          lengthM: 8,
          heatingSides: '4',
          fireLimit: 'R90',
          bearingType: 'Несущая',
          coatingType: 'ТЕХНО ОЗМ'
        }
      ],
      sheet: { areaM2: 0 }
    }
    const enriched = enrichPrefillWithGroups(payload, rows, [
      { title: 'Колонны блок А', rowIds: [2] },
      { title: 'Балки этаж 1', rowIds: [1, 3] }
    ])
    expect(enriched.items[0].rowId).toBe(1)
    expect(enriched.items[1].rowId).toBe(2)
    expect(enriched.groups).toEqual([
      { title: 'Колонны блок А', rowIds: [2] },
      { title: 'Балки этаж 1', rowIds: [1] }
    ])

    const mapped = mapPrefillPayload(enriched, sampleRoll)
    expect(mapped.useGroups).toBe(true)
    expect(mapped.groups).toHaveLength(2)
    expect(mapped.groups[0].title).toBe('Колонны блок А')
    expect(mapped.groups[0].elements[0].element.rollId).toBe('46')
    expect(mapped.groups[1].title).toBe('Балки этаж 1')
    expect(mapped.groups[1].elements[0].element.rollId).toBe('100001')
  })

  it('matches unequal angles and bent profiles written as AхBхt', () => {
    const roll: RollMark[] = [
      { id: '508', shape: 'corner_ue', label: '140/90 x 8', dims: { B: 140, b: 90, t: 8, R: 12, r: 4 } },
      { id: '410', shape: 'corner_e', label: '63 x 5', dims: { b: 63, t: 5, R: 7, r: 2.3 } },
      { id: '13278', shape: 'profile_sm', label: '140/100 x 6', dims: { h: 140, b: 100, t: 6 } }
    ]
    const idx = buildRollIndex(roll)
    expect(matchRoll('140х90х8', roll, idx)?.id).toBe('508')
    expect(matchRoll('63х63х5', roll, idx)?.id).toBe('410')
    expect(matchRoll('140х100х6', roll, idx)?.id).toBe('13278')
    // квадратная запись «140х5» не должна цепляться к «140/90 x 8»
    expect(matchRoll('140х5', roll, idx)).toBeNull()
  })
})
