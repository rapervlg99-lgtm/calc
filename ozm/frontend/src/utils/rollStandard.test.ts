import { describe, expect, it } from 'vitest'
import type { RollMark } from '../types/api'
import { buildJobFromOcr, cleanMark, resolveMassPerMeter, type OcrpdfResult } from './ocrImport'

/**
 * У «40Б2» два стандарта и две разные массы: 66,0342 кг/м по действующему
 * ГОСТ 35087-2024 (400×200×8×13) и 54,7 по недействующему ГОСТ 26020-83
 * (396×165×7,5×11,5). Записи ниже — из настоящего сортамента (roll.json).
 *
 * Масса обязана браться из ГОСТа, указанного в спецификации. Если подтвердить
 * ГОСТ нечем (стандарта нет в сортаменте, марки в нём нет или в поле ГОСТ
 * профиля попал ГОСТ стали), строка помечается «Требует проверки»: молча
 * подставить массу другого стандарта нельзя — для 40Б2 это ошибка в 17 % длины.
 */
const CURRENT: RollMark = {
  id: 'calclab:ivan_v028:3294', shape: 'I-beam_sm', label: '40Б2',
  dims: { h: 400, b: 200, s: 8, t: 13, R: 16 },
  standard: 'ГОСТ 35087-2024', standardLabel: 'ГОСТ 35087-2024 — действующий',
  standardStatus: 'current', familyLabel: 'Балочные нормальные (Б)', massPerMeter: 66.0342
}
const ARCHIVED: RollMark = {
  id: 'calclab:ivan_v028:700', shape: 'I-beam_sm', label: '40Б2',
  dims: { h: 396, b: 165, s: 7.5, t: 11.5, R: 21 },
  standard: 'ГОСТ 26020-83', standardLabel: 'ГОСТ 26020-83 — недействующий',
  standardStatus: 'deprecated', familyLabel: 'Балочные нормальные (Б)', massPerMeter: 54.7
}
/** Тот же стандарт, но другая марка: нужна для случая «стандарт есть, марки в нём нет». */
const CURRENT_40B1: RollMark = {
  ...CURRENT, id: 'calclab:ivan_v028:3293', label: '40Б1',
  dims: { h: 396, b: 199, s: 7, t: 11, R: 16 }, massPerMeter: 56.6456
}

const ROLL: RollMark[] = [CURRENT, ARCHIVED]
const HANDBOOK = new Map<string, number>([['balka/40Б2', 66.0], ['40Б2', 66.0]])

function massByGost(gost: string, roll: RollMark[] = ROLL) {
  return resolveMassPerMeter('40Б2', 'balka', 'Двутавры стальные горячекатаные',
                             HANDBOOK, roll, undefined, gost)
}

/** Ответ OCR по одной строке: марка (с кодом детали, если он есть) и ГОСТ профиля. */
function result(profileStandards: string[], roll: RollMark[] = ROLL, profileSize = '40Б2') {
  const res = {
    type: 'ocrpdf:result',
    job: 'b40',
    filename: 'b40.pdf',
    tables: [{
      index: 1, title: 'Спецификация металлопроката', kind: 'spec_main', part: '', page: 1,
      header_rows: [0], columns: [], rows: [{
        row: 3, kind: 'data', position: 1,
        profile_group: 'Двутавры стальные горячекатаные с параллельными гранями полок',
        steel_grade: 'С245',
        profile_standards: profileStandards,
        steel_standards: ['ГОСТ 27772-2021'],
        standards: ['ГОСТ 27772-2021'],
        profile_size: profileSize, elements: { 'Балки': 1.28 }, total: 1.28, validation: 'ok'
      }]
    }]
  } as OcrpdfResult
  return buildJobFromOcr(res, { roll, handbook: HANDBOOK })
}

describe('масса 40Б2 по ГОСТу из спецификации', () => {
  it('ГОСТ 26020-83 (недействующий) — 54,7 кг/м', () => {
    const { mpm, standardMiss } = massByGost('ГОСТ 26020-83')
    expect(mpm).toBeCloseTo(54.7, 3)
    expect(standardMiss).toBeFalsy()
  })

  it('ГОСТ 35087-2024 (действующий) — 66,03 кг/м', () => {
    const { mpm, standardMiss } = massByGost('ГОСТ 35087-2024')
    expect(mpm).toBeCloseTo(66.0342, 3)
    expect(standardMiss).toBeFalsy()
  })

  it('ГОСТ не указан — масса из прежнего справочника, проверка не нужна', () => {
    const { mpm, standardMiss } = massByGost('')
    expect(mpm).toBeCloseTo(66.0, 3)
    expect(standardMiss).toBeFalsy()
  })

  it('СТО АСЧМ 20-93 не отдельный стандарт сортамента — масса есть, ГОСТ не подтверждён', () => {
    const { mpm, standardMiss } = massByGost('СТО АСЧМ 20-93')
    expect(mpm).toBeCloseTo(66.0, 3)
    expect(standardMiss).toBe(true)
  })

  it('в поле ГОСТ профиля попал ГОСТ стали — масса есть, ГОСТ профиля не подтверждён', () => {
    const { mpm, standardMiss } = massByGost('ГОСТ 27772-2021')
    expect(mpm).toBeCloseTo(66.0, 3)
    expect(standardMiss).toBe(true)
  })

  it('стандарт есть в сортаменте, а марки в нём нет — масса не подставляется', () => {
    const { mpm, standardMiss } = massByGost('ГОСТ 35087-2024', [CURRENT_40B1, ARCHIVED])
    expect(mpm).toBeNull()
    expect(standardMiss).toBe(true)
  })
})

describe('импорт строки 40Б2 из ответа OCR', () => {
  it('берёт ГОСТ профиля, а не ГОСТ стали: 54,7 кг/м, статус «Посчитано»', () => {
    const { job, notes } = result(['ГОСТ 26020-83'])
    const row = job.profileRows[0]
    expect(row.gostProfile).toBe('ГОСТ 26020-83')
    expect(row.massPerMeter).toBeCloseTo(54.7, 3)
    expect(row.lengthM).toBeCloseTo(Math.round((1280 / 54.7) * 100) / 100, 2)
    expect(row.status).toBe('Посчитано')
    expect(notes.some((n) => n.includes('не подтверждён сортаментом'))).toBe(false)
  })

  it('ГОСТ не подтверждён сортаментом: масса из прежнего справочника, но строка на проверку', () => {
    const { job, notes } = result(['СТО АСЧМ 20-93'])
    const row = job.profileRows[0]
    expect(row.massPerMeter).toBeCloseTo(66.0, 3)
    // длина по неверному стандарту короче на 17 % — поэтому и нужна пометка
    expect(row.lengthM).toBeCloseTo(Math.round((1280 / 66.0) * 100) / 100, 2)
    expect(row.status).toBe('Требует проверки')
    expect(notes.some((n) => n.includes('не подтверждён сортаментом'))).toBe(true)
  })

  it('марка есть только в другом стандарте: масса не подставлена и об этом сказано', () => {
    const { job, notes } = result(['ГОСТ 35087-2024'], [CURRENT_40B1, ARCHIVED])
    const row = job.profileRows[0]
    expect(row.massPerMeter).toBe(0)
    expect(row.status).toBe('Нужен ввод массы')
    expect(notes.some((n) => n.includes('марка не найдена'))).toBe(true)
  })

  it('код детали в скобках не мешает найти марку и её ГОСТ', () => {
    // так марка напечатана на KD.163_8: «40Б2 (214-202-0103-0002)»
    expect(cleanMark('40Б2 (214-202-0103-0002)')).toBe('40Б2')
    expect(cleanMark('(214-201-0103-0013) 160х11')).toBe('160х11')
    const { job, notes } = result(['ГОСТ 26020-83'], ROLL, '40Б2 (214-202-0103-0002)')
    const row = job.profileRows[0]
    expect(row.profileMark).toBe('40Б2')
    expect(row.profileRaw).toBe('40Б2 (214-202-0103-0002)')
    expect(row.massPerMeter).toBeCloseTo(54.7, 3)
    expect(row.status).toBe('Посчитано')
    expect(notes.some((n) => n.includes('ГОСТ'))).toBe(false)
  })
})
