import { describe, expect, it } from 'vitest'
import type { RollMark } from '../types/api'
import { buildJobFromOcr, resolveMassPerMeter, type OcrpdfResult } from './ocrImport'

/**
 * file-13: «I20Ш1» прочитано как «2011», буква серии потеряна. ocrpdf отдаёт
 * варианты 20Б1 / 20Ш1 / 20К1 — импорт либо подбирает единственный, что есть
 * в справочнике, либо оставляет выбор пользователю.
 */
const ROLL: RollMark[] = [
  { id: '370', shape: 'I-beam_sm', label: '20 Б1', dims: { h: 200, b: 100, s: 5.5, t: 8, R: 11 } }
]

function result(candidates: string[] | undefined): OcrpdfResult {
  return {
    type: 'ocrpdf:result',
    job: 'abc',
    filename: 'file-13.pdf',
    tables: [
      {
        index: 1, title: 'Спецификация металлопроката', kind: 'spec_main', part: '', page: 1,
        header_rows: [0, 1],
        columns: [
          { index: 0, role: 'profile_group', element: '', letter: '', title: 'Наименование профиля' },
          { index: 1, role: 'steel_grade', element: '', letter: '', title: 'Марка' },
          { index: 2, role: 'profile_size', element: '', letter: '', title: 'Номер профиля' },
          { index: 3, role: 'position', element: '', letter: '', title: 'Поз.' },
          { index: 5, role: 'element_mass', element: 'Балки', letter: '', title: 'Балки' },
          { index: 9, role: 'total_mass', element: '', letter: '', title: 'Общая масса, т' }
        ],
        rows: [
          {
            row: 3, kind: 'data', position: 2,
            profile_group: 'Двутавры стальные горячекатаные с параллельными гранями полок ГОСТ 26020-83',
            steel_grade: 'С345-6', standards: ['ГОСТ 27772-2021'], profile_standards: ['ГОСТ 26020-83'],
            profile_size: '2011', profile_size_candidates: candidates,
            elements: { 'Балки': 2.36 }, total: 2.36, validation: 'ok'
          }
        ]
      }
    ]
  } as OcrpdfResult
}

describe('варианты марки при потерянной букве серии', () => {
  it('единственный вариант из справочника подставляется с пометкой «Требует проверки»', () => {
    const { job, notes } = buildJobFromOcr(result(['20Б1', '20Ш1', '20К1']), { roll: ROLL })
    const row = job.profileRows[0]
    expect(row.profileMark).toBe('20Б1')
    expect(row.profileRaw).toBe('2011')
    expect(row.massPerMeter).toBeGreaterThan(20)
    expect(row.lengthM).toBeGreaterThan(0)
    expect(row.status).toBe('Требует проверки')
    expect(row.profileCandidates).toBeUndefined()
    expect(notes.some((n) => n.includes('подобрана по справочнику'))).toBe(true)
  })

  it('несколько вариантов в справочнике — выбор остаётся за пользователем', () => {
    const handbook = new Map<string, number>([['balka/20Б1', 21.3], ['balka/20Ш1', 30.6]])
    const { job, notes } = buildJobFromOcr(result(['20Б1', '20Ш1', '20К1']), { handbook })
    const row = job.profileRows[0]
    expect(row.profileMark).toBe('2011')
    expect(row.status).toBe('Нужен ввод массы')
    expect(row.profileCandidates).toEqual([
      { mark: '20Б1', massPerMeter: 21.3, source: 'cache' },
      { mark: '20Ш1', massPerMeter: 30.6, source: 'cache' }
    ])
    expect(notes.some((n) => n.includes('выберите марку'))).toBe(true)
  })

  it('ни одного варианта в справочнике — показываем все с нулевой массой', () => {
    const { job } = buildJobFromOcr(result(['20Б1', '20Ш1', '20К1']), {})
    const row = job.profileRows[0]
    expect(row.profileMark).toBe('2011')
    expect(row.profileCandidates?.map((c) => c.mark)).toEqual(['20Б1', '20Ш1', '20К1'])
    expect(row.profileCandidates?.every((c) => c.massPerMeter === 0)).toBe(true)
  })

  it('без вариантов поведение прежнее', () => {
    const { job } = buildJobFromOcr(result(undefined), { roll: ROLL })
    const row = job.profileRows[0]
    expect(row.profileMark).toBe('2011')
    expect(row.status).toBe('Нужен ввод массы')
    expect(row.profileCandidates).toBeUndefined()
  })

  it('resolveMassPerMeter: справочник масс важнее расчёта по сечению', () => {
    const handbook = new Map<string, number>([['balka/20Б1', 21.3]])
    expect(resolveMassPerMeter('20Б1', 'balka', 'Двутавры', handbook, ROLL, undefined)).toEqual({ mpm: 21.3, source: 'cache' })
    const viaRoll = resolveMassPerMeter('20Б1', 'balka', 'Двутавры', undefined, ROLL, undefined)
    expect(viaRoll.source).toBe('formula')
    expect(viaRoll.mpm).toBeGreaterThan(20)
    expect(resolveMassPerMeter('20Ш1', 'balka', 'Двутавры', undefined, ROLL, undefined)).toEqual({ mpm: null, source: '' })
  })
})
