import { describe, expect, it } from 'vitest'
import type { RollMark } from '../types/api'
import { angleMassPerMeterFromMark, buildJobFromOcr, resolveMassPerMeter, type OcrpdfResult } from './ocrImport'

/**
 * file-13, поз. 14–15: уголки «150х150х10» и «180х180х15». Серии 150 не было
 * ни в одном справочнике (добавлена в оба), «180х180х15» в ГОСТ 8509-93 нет
 * вовсе — масса считается по размерам из марки. У поз. 15 графа наименования
 * на чертеже пустая — группа переносится со строки выше.
 */
const ROLL: RollMark[] = [
  { id: '100029', shape: 'corner_e', label: '150 x 10', dims: { b: 150, t: 10, R: 16, r: 5.3 } }
]

function result(): OcrpdfResult {
  return {
    type: 'ocrpdf:result',
    job: 'f13',
    filename: 'file-13.pdf',
    tables: [
      {
        index: 1, title: 'Спецификация металлопроката', kind: 'spec_main', part: '', page: 1,
        header_rows: [0, 1],
        columns: [
          { index: 0, role: 'profile_group', element: '', letter: '', title: 'Наименование профиля' },
          { index: 2, role: 'profile_size', element: '', letter: '', title: 'Номер профиля' },
          { index: 3, role: 'position', element: '', letter: '', title: 'Поз.' },
          { index: 6, role: 'element_mass', element: 'Связи вертикальные', letter: '', title: 'Связи вертикальные' },
          { index: 8, role: 'element_mass', element: 'Прогоны', letter: '', title: 'Прогоны' },
          { index: 9, role: 'total_mass', element: '', letter: '', title: 'Общая масса, т' }
        ],
        rows: [
          {
            row: 13, kind: 'data', position: 14,
            profile_group: 'Уголки стальные горячекатаные равнополочные ГОСТ 8509-93',
            steel_grade: 'С345-6', standards: ['ГОСТ 27772-2021'], profile_standards: ['ГОСТ 8509-93'],
            profile_size: '150х150х10', elements: { 'Связи вертикальные': 2.53 }, total: 2.53, validation: 'ok'
          },
          {
            row: 14, kind: 'data', position: 15,
            profile_group: '', steel_grade: 'С345-6', standards: ['ГОСТ 27772-2021'], profile_standards: [],
            profile_size: '180х180х15', elements: { 'Прогоны': 1.51 }, total: 1.51, validation: 'ok'
          },
          {
            row: 15, kind: 'profile_total', position: 16, profile_group: 'Всего профиля:', steel_grade: '',
            standards: [], profile_size: null, elements: { 'Связи вертикальные': 2.53, 'Прогоны': 1.51 }, total: 4.04, validation: 'ok'
          },
          {
            // после строки-итога пустая графа наименования уже не наследуется
            row: 16, kind: 'data', position: 17, profile_group: '', steel_grade: 'С345-6', standards: [],
            profile_size: '120х120х6', elements: { 'Прогоны': 1.0 }, total: 1.0, validation: 'ok'
          }
        ]
      }
    ]
  } as OcrpdfResult
}

describe('масса уголка по размерам из марки', () => {
  it('равнополочный и неравнополочный, только для категории уголков', () => {
    expect(angleMassPerMeterFromMark('ygolok', '150х150х10')).toBeCloseTo(22.77, 1)   // ГОСТ: 23,02
    expect(angleMassPerMeterFromMark('ygolok', 'L 75х6')).toBeCloseTo(6.78, 1)          // ГОСТ: 6,89
    expect(angleMassPerMeterFromMark('ygolok', '180х180х15')).toBeCloseTo(40.62, 1)
    expect(angleMassPerMeterFromMark('ygolok', '140х90х8')).toBeCloseTo(13.94, 1)       // ГОСТ 8510: 14,13
    expect(angleMassPerMeterFromMark('ygolok_gnyt', '100х100х4')).toBeCloseTo(6.15, 1)
    expect(angleMassPerMeterFromMark('tryba_es_kvadr', '120х120х6')).toBe(0)
    expect(angleMassPerMeterFromMark('', '180х180х15')).toBe(0)
    expect(angleMassPerMeterFromMark('ygolok', '20Б1')).toBe(0)
    expect(angleMassPerMeterFromMark('ygolok', '150х150х150')).toBe(0)                 // толщина не меньше полки
  })

  it('формула — последний рубеж после справочников', () => {
    const handbook = new Map<string, number>([['ygolok/150Х150Х10', 23.02]])
    expect(resolveMassPerMeter('150х150х10', 'ygolok', 'Уголки', handbook, [], undefined)).toEqual({ mpm: 23.02, source: 'cache' })
    const viaRoll = resolveMassPerMeter('150х150х10', 'ygolok', 'Уголки', undefined, ROLL, undefined)
    expect(viaRoll.source).toBe('formula')
    expect(viaRoll.mpm).toBeCloseTo(23.1, 0)
    const viaMark = resolveMassPerMeter('180х180х15', 'ygolok', 'Уголки', undefined, ROLL, undefined)
    expect(viaMark).toEqual({ mpm: 40.62, source: 'formula' })
  })
})

describe('пустая графа наименования наследует группу строки выше', () => {
  it('file-13: поз. 15 становится уголком и получает массу по формуле', () => {
    const { job, notes } = buildJobFromOcr(result(), { roll: ROLL })
    const [r14, r15, r17] = job.profileRows
    expect(r14.profileMark).toBe('150х150х10')
    expect(r14.massPerMeter).toBeCloseTo(23.1, 0)
    expect(r14.status).toBe('Требует проверки')
    expect(r15.profileMark).toBe('180х180х15')
    expect(r15.name).toBe('Уголки стальные горячекатаные равнополочные')
    expect(r15.gostProfile).toBe('ГОСТ 8509-93')
    expect(r15.massPerMeter).toBe(40.62)
    expect(r15.massSource).toBe('formula')
    expect(r15.status).toBe('Требует проверки')
    expect(r15.lengthM).toBeCloseTo(1510 / 40.62, 1)
    // после «Всего профиля» наследование сброшено: категория неизвестна, массы нет
    expect(r17.name).toBe('Элемент')
    expect(r17.massPerMeter).toBe(0)
    expect(r17.status).toBe('Нужен ввод массы')
    expect(notes.some((n) => n.includes('взято со строки выше'))).toBe(true)
  })
})
