import { describe, expect, it } from 'vitest'
import type { RollMark } from '../types/api'
import { shapesForRow } from '../fixtures/demoJob'
import { mapPrefillItem } from './prefillMapper'
import {
  buildJobFromOcr,
  cleanMark,
  constructionName,
  defaultShapeFor,
  rollMarkCandidates,
  handbookKey,
  handbookMarkFor,
  isOcrpdfResult,
  isServiceGroup,
  isSheetRow,
  lookupHandbook,
  massPerMeterFromDims,
  ocrJobId,
  profileCategory,
  profileFamilyLabel,
  sheetThicknessMm,
  type OcrpdfResult
} from './ocrImport'

const ROLL: RollMark[] = [
  { id: '370', shape: 'I-beam_sm', label: '20 Б1', dims: { h: 200, b: 100, s: 5.5, t: 8, R: 11 } },
  { id: '7901', shape: 'tube_sq', label: '140 x 5', dims: { A: 140, s: 5 } },
  { id: '955', shape: 'corner_e', label: '100 x 8', dims: { b: 100, t: 8, R: 12, r: 4 } }
]

/** Фрагмент реального результата ocrpdf по листу file-3 (487): спецификация 25×9. */
function sample(): OcrpdfResult {
  return {
    type: 'ocrpdf:result',
    job: 'ed8d808aa8a944a69d5f7f5de150ca48',
    filename: 'file-3 (487).pdf',
    tables: [
      {
        index: 2, title: 'Спецификация металлопроката', kind: 'spec_main', part: '', page: 1,
        header_rows: [0, 1, 2],
        columns: [
          { index: 0, role: 'profile_group', element: '', letter: '', title: 'Наименование профиля' },
          { index: 1, role: 'steel_grade', element: '', letter: '', title: 'Наименование или марка металла' },
          { index: 2, role: 'profile_size', element: '', letter: '', title: 'Номер или размеры профиля' },
          { index: 3, role: 'position', element: '', letter: '', title: '№ п.п.' },
          { index: 4, role: 'element_mass', element: 'Фермы', letter: '', title: 'Фермы' },
          { index: 5, role: 'element_mass', element: 'Связи, распорки', letter: '', title: 'Связи, распорки' },
          { index: 8, role: 'total_mass', element: '', letter: '', title: 'Общая масса, т' }
        ],
        checks: [{ row: 13, status: 'failed' }],
        rows: [
          { row: 3, kind: 'data', position: 1, profile_group: 'Профиль стальной гнутый замкнутый сварной квадратный ГОСТ 30245-2012',
            steel_grade: 'С255-5\nГОСТ 27772-2021', standards: ['ГОСТ 27772-2021'], profile_size: '□140х5',
            elements: { 'Фермы': 7.21, 'Связи, распорки': null }, total: 22.01, validation: 'ok' },
          { row: 8, kind: 'group_total', position: 6, profile_group: '', steel_grade: 'Итого:', standards: [],
            profile_size: null, elements: { 'Фермы': 10.72 }, total: 32.752, validation: 'ok' },
          { row: 10, kind: 'data', position: 8, profile_group: 'Уголок равнополочный ГОСТ 8509-93',
            steel_grade: 'С255-5', standards: ['ГОСТ 27772-2021'], profile_size: 'L 100х8',
            elements: { 'Фермы': null, 'Связи, распорки': 0.145 }, total: 0.145, validation: 'ok' },
          { row: 13, kind: 'data', position: 11, profile_group: 'Двутавры стальные горячекатаные ГОСТ Р 57837-2017',
            steel_grade: 'С345', standards: [], profile_size: '20Б1',
            elements: { 'Фермы': 2.13, 'Связи, распорки': 0.5 }, total: 2.63, validation: 'failed' },
          { row: 15, kind: 'data', position: 13, profile_group: 'Сталь листовая горячекатанная ГОСТ 19903-2015',
            steel_grade: 'С255-5', standards: ['ГОСТ 27772-2021'], profile_size: 'δ=4 мм',
            elements: { 'Фермы': 0.035 }, total: 0.2, validation: 'ok' },
          { row: 16, kind: 'data', position: 14, profile_group: 'Профиль неизвестный', steel_grade: '',
            standards: [], profile_size: '999х9', elements: {}, total: 1.0, validation: 'ok' }
        ]
      },
      { index: 4, title: 'Таблица', kind: 'unreadable', part: '', page: 1, header_rows: [], columns: [], rows: [] },
      // разбивка итогов по маркам стали — в форму не импортируется
      { index: 3, title: 'В том числе по маркам или наименованиям', kind: 'mass_by_grade', part: '', page: 1,
        header_rows: [], columns: [
          { index: 0, role: 'profile_group', element: '', letter: '', title: '' },
          { index: 2, role: 'profile_size', element: '', letter: '', title: '' },
          { index: 4, role: 'element_mass', element: 'Фермы', letter: '', title: 'Фермы' }
        ],
        rows: [{ row: 24, kind: 'data', position: 21, profile_group: 'С255-5', steel_grade: '', standards: [],
                 profile_size: null, elements: { 'Фермы': 12.45 }, total: 36.72, validation: 'ok' }] }
    ]
  }
}

describe('ocrImport helpers', () => {
  it('detects the postMessage payload', () => {
    expect(isOcrpdfResult(sample())).toBe(true)
    expect(isOcrpdfResult({ type: 'other' })).toBe(false)
    expect(isOcrpdfResult(null)).toBe(false)
  })

  it('strips profile-type glyphs from marks', () => {
    expect(cleanMark('□140х5')).toBe('140х5')
    expect(cleanMark('L 100х8')).toBe('100х8')
    expect(cleanMark('Ι 20Б1')).toBe('20Б1')
    expect(cleanMark('20Б1')).toBe('20Б1')
    expect(cleanMark('δ=4 мм')).toBe('δ=4')
  })

  it('builds handbook keys like sortament.Normalize', () => {
    expect(handbookKey('□140х5')).toBe('140Х5')
    expect(handbookKey('L 100x8')).toBe('100Х8')
    expect(handbookKey('20B1')).toBe('20Б1')
    expect(handbookKey('35W2')).toBe('35Ш2')
    expect(handbookKey('20 Б1')).toBe('20Б1')
    expect(handbookKey('16У')).toBe('16У')
  })

  it('reads sheet thickness', () => {
    expect(sheetThicknessMm('δ=4 мм')).toBe(4)
    expect(sheetThicknessMm('t8')).toBe(8)
    expect(sheetThicknessMm('-6')).toBe(6)
    expect(sheetThicknessMm('20Б1')).toBeNull()
    expect(isSheetRow({ profile_group: 'Сталь листовая', profile_size: 't10' })).toBe(true)
    expect(isSheetRow({ profile_group: 'Прокат горячекатаный', profile_size: 't40' })).toBe(true)
    expect(isSheetRow({ profile_group: 'Уголок', profile_size: 'L 75х6' })).toBe(false)
    expect(isSheetRow({ profile_group: 'Трубы', profile_size: '57х3' })).toBe(false)
  })

  it('estimates mass per metre from section dims within a few percent of the handbook', () => {
    expect(massPerMeterFromDims('I-beam_sm', ROLL[0].dims)).toBeCloseTo(21.3, 0)   // 20Б1 → 21,3 кг/м
    expect(massPerMeterFromDims('tube_sq', ROLL[1].dims)).toBeCloseTo(20.9, 0)     // 140х5 → 20,9 кг/м
    expect(massPerMeterFromDims('corner_e', ROLL[2].dims)).toBeCloseTo(12.25, 0)   // L100х8 → 12,25 кг/м
    expect(massPerMeterFromDims('brands_sm', { h: 3, b: 18 })).toBeNull()
  })

  it('derives the sortament category from group name, GOST or mark glyph', () => {
    expect(profileCategory('Двутавры стальные горячекатаные ГОСТ Р 57837-2017', '', '20Б1')).toBe('balka')
    expect(profileCategory('', '', '20Б1')).toBe('balka')
    expect(profileCategory('Швеллеры стальные горячекатаные ГОСТ 8240-97', '', '20П')).toBe('shveller')
    expect(profileCategory('Уголок равнополочный ГОСТ 8509-93', '', 'L 100х8')).toBe('ygolok')
    expect(profileCategory('', '', 'L 100х8')).toBe('ygolok')
    expect(profileCategory('Профиль стальной гнутый замкнутый сварной квадратный ГОСТ 30245-2012', '', '□140х5')).toBe('tryba_es_kvadr')
    expect(profileCategory('', '', '□140х5')).toBe('tryba_es_kvadr')
    // форму замкнутого профиля решает марка, не одно слово из названия группы
    expect(profileCategory('Профили стальные гнутые замкнутые сварные прямоугольные', 'ГОСТ 30245-2003', '140х140х4')).toBe('tryba_es_kvadr')
    expect(profileCategory('Профили стальные гнутые замкнутые сварные квадратные', 'ГОСТ 30245-2003', '140х100х4')).toBe('tryba_es_pr')
    expect(profileCategory('Профили стальные гнутые замкнутые сварные прямоугольные', '', '140х4')).toBe('tryba_es_pr')
    expect(profileCategory('Прокат листовой', '', 'δ=4')).toBe('')
    expect(handbookMarkFor('ygolok', 'L 100х8')).toBe('100Х100Х8')
    expect(handbookMarkFor('tryba_es_kvadr', '□100х8')).toBe('100Х8')
    expect(handbookKey('25ШО')).toBe('25Ш0') // «О» вместо нуля после серии
    expect(handbookKey('I25WO')).toBe('25Ш0')
    expect(handbookKey('25Ш1')).toBe('25Ш1')
  })

  it('resolves an ambiguous dimensional mark by category', () => {
    const handbook = new Map<string, number>([
      ['tryba_es_kvadr/100Х8', 21.39],
      ['ygolok/100Х100Х8', 12.25]
    ])
    expect(lookupHandbook(handbook, 'ygolok', 'L 100х8')).toBe(12.25)
    expect(lookupHandbook(handbook, 'tryba_es_kvadr', '□100х8')).toBe(21.39)
    // «140Х4» без категории неоднозначна (круглая и квадратная труба):
    // из «прямоугольной» группы заглядываем в квадратные
    const tubes = new Map<string, number>([
      ['tryba_es_krug/140Х4', 13.42], ['tryba_es_kvadr/140Х4', 16.76]
    ])
    expect(lookupHandbook(tubes, 'tryba_es_pr', '140х4')).toBe(16.76)
    expect(lookupHandbook(tubes, 'tryba_es_pr', '140х140х4')).toBe(16.76)
    expect(lookupHandbook(tubes, 'tryba_es_krug', '140х4')).toBe(13.42)
    expect(lookupHandbook(handbook, '', '100х8')).toBeUndefined()
    // без справочника — по размерам, но только среди форм своей категории
    const roll: RollMark[] = [
      { id: '1', shape: 'tube_sq', label: '100 x 8', dims: { A: 100, s: 8 } },
      { id: '2', shape: 'corner_e', label: '100 x 8', dims: { b: 100, t: 8, R: 12, r: 4 } }
    ]
    const res: OcrpdfResult = {
      ...sample(),
      tables: [{ ...sample().tables[0], rows: [{
        row: 10, kind: 'data', position: 8, profile_group: 'Уголок равнополочный ГОСТ 8509-93',
        steel_grade: 'С255', standards: [], profile_size: 'L 100х8',
        elements: { 'Фермы': 1.225 }, total: 1.225, validation: 'ok' }] }]
    }
    const { job } = buildJobFromOcr(res, { roll })
    expect(job.profileRows[0].massPerMeter).toBeCloseTo(12.25, 0)
    expect(job.profileRows[0].lengthM).toBeCloseTo(100, -1)
  })

  it('never matches a roll entry by substring («140х5» is not «40 x 5»)', () => {
    const roll: RollMark[] = [{ id: '9', shape: 'tube_sq', label: '40 x 5', dims: { A: 40, s: 5 } }]
    const res: OcrpdfResult = {
      ...sample(),
      tables: [{ ...sample().tables[0], rows: [{
        row: 3, kind: 'data', position: 1, profile_group: 'Профиль стальной гнутый замкнутый сварной квадратный',
        steel_grade: 'С255', standards: [], profile_size: '□140х5',
        elements: { 'Фермы': 7.21 }, total: 7.21, validation: 'ok' }] }]
    }
    const { job } = buildJobFromOcr(res, { roll })
    expect(job.profileRows[0].status).toBe('Нужен ввод массы')
    expect(job.profileRows[0].massPerMeter).toBe(0)
  })

  it('prefill honours the shape hint so a square tube is not mapped to a round one', () => {
    const roll: RollMark[] = [
      { id: '1', shape: 'tube_sm', label: '140 x 5', dims: { d: 140, h: 5 } },
      { id: '2', shape: 'tube_sq', label: '140 x 5', dims: { A: 140, s: 5 } }
    ]
    const item = { profileMark: '140х5', lengthM: 10, heatingSides: '4', fireLimit: 'R90', bearingType: '', coatingType: '' }
    expect(mapPrefillItem(item, roll).element.shape).toBe('tube_sm') // без подсказки — первая попавшаяся
    expect(mapPrefillItem({ ...item, shapes: ['tube_sq'] }, roll).element.shape).toBe('tube_sq')
    expect(mapPrefillItem({ ...item, shapes: ['tube_sq'] }, roll).element.rollId).toBe('2')
    const row = buildJobFromOcr(sample(), { roll: ROLL }).job.profileRows[0]
    expect(shapesForRow(row)).toEqual(['tube_sq'])
  })

  it('takes the profile family from the group name even without a roll hit', () => {
    expect(profileCategory('Швеллеры стальные горячекатаные', '', '')).toBe('shveller')
    expect(profileCategory('Двутавры стальные горячекатаные', '', '')).toBe('balka')
    expect(profileCategory('Трубы стальные электросварные прямошовные', '', '57х3')).toBe('tryba_es_krug')
    expect(profileCategory('Тавры стальные', '', '')).toBe('tavr')
    expect(profileCategory('Уголки стальные горячекатаные равнополочные', '', '')).toBe('ygolok')
    expect(defaultShapeFor('shveller')).toBe('channel_')
    expect(defaultShapeFor('')).toBeUndefined()
    // калькулятор: марка «99П» не в справочнике, но по группе это швеллер
    const row = { ...buildJobFromOcr(sample(), { roll: ROLL }).job.profileRows[0],
      name: 'Швеллеры стальные горячекатаные', gostProfile: 'ГОСТ 8240-97', profileRaw: '99П', profileMark: '99П' }
    const shapes = shapesForRow(row)
    expect(shapes).toEqual(['channel_', 'channel_sl'])
    const mapped = mapPrefillItem({ profileMark: '99П', lengthM: 3, heatingSides: '4', fireLimit: 'R60',
      bearingType: '', coatingType: '', shapes }, ROLL)
    expect(mapped.profileMiss).toBe(true)
    expect(mapped.element.shape).toBe('channel_')
  })

  it('finds three-number angle marks in the roll dict and blanks unnamed construction columns', () => {
    expect(rollMarkCandidates('ygolok', 'L150х150х10'.replace(/^L/, ''))).toEqual(['150х150х10', '150х10'])
    expect(rollMarkCandidates('ygolok', '150х100х10')).toEqual(['150х100х10', '150/100х10'])
    expect(rollMarkCandidates('balka', '20Б1')).toEqual(['20Б1'])
    expect(rollMarkCandidates('tryba_es_pr', '200х200х7')).toEqual(['200х200х7', '200х7'])
    expect(rollMarkCandidates('tryba_es_kvadr', 'D40х40х4')).toEqual(['D40х40х4', '40х40х4', '40х4'])
    expect(handbookMarkFor('tryba_es_pr', '200х200х7')).toBe('200Х7')
    expect(handbookMarkFor('tryba_es_pr', '200х100х7')).toBe('200Х100Х7')
    expect(constructionName('col8')).toBe('')
    expect(constructionName('Фермы')).toBe('Фермы')
    const roll: RollMark[] = [{ id: '7', shape: 'corner_e', label: '150 x 10', dims: { b: 150, t: 10, R: 16, r: 5.3 } }]
    const res: OcrpdfResult = {
      ...sample(),
      tables: [{ ...sample().tables[0], rows: [{
        row: 13, kind: 'data', position: 12, profile_group: 'Уголки стальные горячекатаные равнополочные',
        steel_grade: 'С255', standards: ['ГОСТ 27772-2021'], profile_size: 'L150х150х10',
        elements: { col6: 2.53 }, total: 2.53, validation: 'ok' }] }]
    }
    const { job } = buildJobFromOcr(res, { roll })
    const row = job.profileRows[0]
    expect(row.construction).toBe('')
    expect(row.massPerMeter).toBeCloseTo(23, 0) // ГОСТ 8509: 150х150х10 → 23,0 кг/м
    expect(row.status).toBe('Требует проверки')
    expect(row.lengthM).toBeCloseTo(2530 / row.massPerMeter, 1)
  })

  it('prefill does not treat «130К1» as a spelling of «30К1»', () => {
    const roll: RollMark[] = [{ id: '5', shape: 'I-beam_sm', label: '30 К1', dims: { h: 298, b: 299, s: 9, t: 14, R: 15 } }]
    const base = { lengthM: 1, heatingSides: '4', fireLimit: 'R90', bearingType: '', coatingType: '' }
    expect(mapPrefillItem({ ...base, profileMark: '30К1' }, roll).profileMiss).toBe(false)
    expect(mapPrefillItem({ ...base, profileMark: 'I30Б1'.replace('Б', 'К') }, roll).profileMiss).toBe(false)
    const wrong = mapPrefillItem({ ...base, profileMark: '130К1', shapes: ['I-beam_', 'I-beam_sm', 'I-beam_sl'] }, roll)
    expect(wrong.profileMiss).toBe(true)
    expect(wrong.element.shape).toBe('I-beam_')
  })

  it('prefers the profile GOST over the steel GOST and labels the profile family', () => {
    const res: OcrpdfResult = {
      ...sample(),
      tables: [{ ...sample().tables[0], rows: [
        { row: 3, kind: 'data', position: 1, profile_group: 'Двутавры стальные горячекатаные с параллельными гранями полок',
          steel_grade: 'С355', standards: ['ГОСТ 27772-2021'], profile_standards: ['ГОСТ Р 57837-2017'],
          steel_standards: ['ГОСТ 27772-2021'], profile_size: '35Ш2', elements: { 'Фермы': 1 }, total: 1, validation: 'ok' },
        { row: 4, kind: 'data', position: 2, profile_group: 'Швеллеры стальные горячекатаные',
          steel_grade: 'С255', standards: ['ГОСТ 27772-2021'], profile_size: '20П', elements: { 'Фермы': 1 }, total: 1, validation: 'ok' },
        { row: 5, kind: 'data', position: 3, profile_group: 'Прокат листовой горячекатаный',
          steel_grade: 'С255', standards: [], profile_standards: ['ГОСТ 19903-2015'], profile_size: 't10',
          elements: { 'Фермы': 1 }, total: 1, validation: 'ok' }
      ] }]
    }
    const { job } = buildJobFromOcr(res, {})
    expect(job.profileRows[0].gostProfile).toBe('ГОСТ Р 57837-2017')
    expect(job.profileRows[1].gostProfile).toBe('ГОСТ 27772-2021') // старый формат: единственное поле
    expect(job.sheetRows[0].gostProfile).toBe('ГОСТ 19903-2015')
    expect(profileFamilyLabel(job.profileRows[0])).toBe('Двутавр')
    expect(profileFamilyLabel(job.profileRows[1])).toBe('Швеллер')
    expect(profileFamilyLabel(job.sheetRows[0])).toBe('Лист')
    expect(profileFamilyLabel({ name: 'Элемент', gostProfile: '', profileRaw: '', profileMark: '', isSheet: false })).toBe('')
    expect(profileFamilyLabel({ name: 'Профиль стальной гнутый замкнутый сварной квадратный', gostProfile: '', profileRaw: '□140х5', profileMark: '140х5', isSheet: false })).toBe('Труба квадратная')
  })

  it('never borrows the steel GOST when the profile GOST is missing', () => {
    const res: OcrpdfResult = {
      ...sample(),
      tables: [{ ...sample().tables[0], rows: [
        { row: 15, kind: 'data', position: 13, profile_group: 'Профили стальные гнутые замкнутые сварные прямоугольные',
          steel_grade: 'С255', standards: ['ГОСТ 27772-2021'], profile_standards: [],
          steel_standards: ['ГОСТ 27772-2021'], profile_size: '160х160х5', elements: { 'Балки': 1 }, total: 1, validation: 'ok' }
      ] }]
    }
    const { job } = buildJobFromOcr(res, {})
    expect(job.profileRows[0].gostProfile).toBe('')
    expect(job.profileRows[0].steelGrade).toBe('С255')
    expect(profileFamilyLabel(job.profileRows[0])).toBe('Труба квадратная') // 160х160х5 — квадратная
  })

  it('drops steel-grade totals and percentage allowances that leaked into the spec', () => {
    for (const g of ['С255-5', '5553', 'С3556', '0663', '€390', '(345', 'масса. наплабленного металла. 1%', 'Неучтённый металл 2%'])
      expect(isServiceGroup(g)).toBe(true)
    for (const g of ['Прокат горячекатаный', 'Двутавры стальные горячекатаные', 'Профнастил'])
      expect(isServiceGroup(g)).toBe(false)
    const res: OcrpdfResult = {
      ...sample(),
      tables: [{ ...sample().tables[0], rows: [
        { row: 34, kind: 'data', position: 30, profile_group: 'Прокат горячекатаный', steel_grade: 'С355',
          standards: [], profile_size: 't20', elements: { 'Фермы': 0.63 }, total: 0.63, validation: 'ok' },
        { row: 54, kind: 'data', position: null, profile_group: '5553', steel_grade: '5553',
          standards: [], profile_size: null, elements: { 'Фермы': 168.01 }, total: 168.01, validation: 'ok' },
        { row: 57, kind: 'data', position: null, profile_group: 'масса. наплабленного металла. 1%', steel_grade: '',
          standards: [], profile_size: null, elements: { 'Фермы': 3.93 }, total: 3.93, validation: 'ok' }
      ] }]
    }
    const { job, skipped } = buildJobFromOcr(res, {})
    expect(job.profileRows).toHaveLength(0)
    expect(job.sheetRows).toHaveLength(1)
    expect(job.sheetRows[0].profileMark).toBe('t20')
    expect(skipped).toBe(2)
  })

  it('makes a stable local job id', () => {
    expect(ocrJobId('ed8d808aa8a944a69d5f7f5de150ca48')).toBe('ocr-ed8d808aa8a9')
  })
})

describe('buildJobFromOcr', () => {
  it('fans spec rows out per construction column and skips totals', () => {
    const { job, skipped } = buildJobFromOcr(sample(), { roll: ROLL, now: '2026-09-03T00:00:00Z' })
    expect(job.id).toBe('ocr-ed8d808aa8a9')
    expect(job.status).toBe('ready')
    expect(job.confirmed).toBe(false)
    expect(skipped).toBe(1) // строка «Итого»
    const marks = job.profileRows.map((r) => `${r.profileMark}/${r.construction}`)
    expect(marks).toEqual([
      '140х5/Фермы',
      '100х8/Связи, распорки',
      '20Б1/Фермы',
      '20Б1/Связи, распорки',
      '999х9/'
    ])
    expect(job.profileRows.every((r) => r.massUnit === 'kg')).toBe(true)
    expect(job.profileRows[0].mass).toBe(7210)
    expect(job.profileRows[0].ppNumber).toBe('1')
    expect(job.profileRows[0].steelGrade).toBe('С255-5')
    expect(job.profileRows[0].gostProfile).toBe('ГОСТ 27772-2021')
    expect(job.profileRows[0].name).toBe('Профиль стальной гнутый замкнутый сварной квадратный')
  })

  it('computes length from mass via section dims and flags it for review', () => {
    const { job } = buildJobFromOcr(sample(), { roll: ROLL })
    const tube = job.profileRows[0]
    expect(tube.massSource).toBe('formula')
    expect(tube.status).toBe('Требует проверки')
    expect(tube.massPerMeter).toBeGreaterThan(19)
    expect(tube.lengthM).toBeCloseTo(7210 / tube.massPerMeter, 1)
    // профиль, которого нет в справочнике проката
    const unknown = job.profileRows[4]
    expect(unknown.status).toBe('Нужен ввод массы')
    expect(unknown.lengthM).toBe(0)
    expect(unknown.mass).toBe(1000)
  })

  it('prefers the server handbook and marks such rows as calculated', () => {
    const handbook = new Map<string, number>([['20Б1', 21.3], ['140Х5', 20.9]])
    const { job } = buildJobFromOcr(sample(), { roll: ROLL, handbook })
    const tube = job.profileRows[0]
    expect(tube.massSource).toBe('cache')
    expect(tube.massPerMeter).toBe(20.9)
    expect(tube.lengthM).toBeCloseTo(345, 0)
    expect(tube.status).toBe('Посчитано')
    // строка с проваленной арифметикой остаётся на проверке даже со справочником
    const beam = job.profileRows.find((r) => r.profileMark === '20Б1')!
    expect(beam.status).toBe('Требует проверки')
    expect(beam.lengthM).toBeCloseTo(2130 / 21.3, 1)
  })

  it('puts sheet steel into sheetRows with area from thickness', () => {
    const { job } = buildJobFromOcr(sample(), { roll: ROLL })
    expect(job.sheetRows).toHaveLength(1)
    const sheet = job.sheetRows[0]
    expect(sheet.isSheet).toBe(true)
    expect(sheet.massPerMeter).toBeCloseTo(31.4, 1) // кг/м² при δ=4
    expect(sheet.areaM2).toBeCloseTo(35 / 31.4, 1)
    expect(sheet.status).toBe('Посчитано')
  })

  it('reports an empty import', () => {
    const empty: OcrpdfResult = { type: 'ocrpdf:result', job: 'abc', filename: 'x.pdf', tables: [] }
    const { job, notes } = buildJobFromOcr(empty)
    expect(job.profileRows).toHaveLength(0)
    expect(notes[0]).toMatch(/нет строк/)
  })
})

describe('file-45: гнутые трубы и круглый профиль', () => {
  it('cleanMark drops the «Гн» prefix of bent profiles', async () => {
    const { cleanMark } = await import('./ocrImport')
    expect(cleanMark('Гн 100х5')).toBe('100х5')
    expect(cleanMark('Гн.□120х5')).toBe('120х5')
    expect(cleanMark('□ 140х5')).toBe('140х5')
    expect(cleanMark('25Б1')).toBe('25Б1')
  })

  it('round bar mass per metre is derived from the diameter', async () => {
    const { roundBarDiameterMm, roundBarMassPerMeter } = await import('./ocrImport')
    expect(roundBarDiameterMm('RD18', 'Круглый профиль EN 10060')).toBe(18)
    expect(roundBarDiameterMm('Ø 20', '')).toBe(20)
    expect(roundBarDiameterMm('d18', 'Круг стальной')).toBe(18)
    expect(roundBarDiameterMm('d18', 'Двутавры')).toBe(0)
    expect(roundBarDiameterMm('100х5', 'Круг')).toBe(0)
    expect(roundBarMassPerMeter(18)).toBeCloseTo(2.0, 1)
    expect(roundBarMassPerMeter(20)).toBeCloseTo(2.47, 1)
  })
})

describe('trailing profile glyph in marks from the text layer', () => {
  it('is dropped only after a complete designation', async () => {
    const { cleanMark } = await import('./ocrImport')
    expect(cleanMark('25Б1 1')).toBe('25Б1')
    expect(cleanMark('25Б1 т')).toBe('25Б1')
    expect(cleanMark('25х3 □')).toBe('25х3')
    expect(cleanMark('8П С')).toBe('8П')
    expect(cleanMark('Гн 100х5 □')).toBe('100х5')
    expect(cleanMark('Ромб 12')).toBe('Ромб 12')
    expect(cleanMark('Н75-750-0,8')).toBe('Н75-750-0,8')
  })
})
