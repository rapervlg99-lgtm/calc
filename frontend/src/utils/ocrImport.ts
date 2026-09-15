/**
 * Импорт результата локального OCR-сервиса (ocrpdf, «Распознавание таблиц из
 * проектных PDF») в задание формы ОГЗ.
 *
 * Страница OCR открывается во фрейме на /recognize и по нажатию «Передать в
 * калькулятор» шлёт postMessage `{type:"ocrpdf:result", tables:[...]}`. Здесь
 * строки спецификации превращаются в OgzRow — те же строки, что даёт серверный
 * пайплайн /ext и демо-форма, — и дальше работает обычная форма ОГЗ → prefill.
 *
 * Одна строка спецификации даёт по строке ОГЗ на каждую колонку «масса по
 * элементам конструкций» с ненулевой массой (как в backend/recognition).
 * Длина считается из массы: масса ÷ погонная масса. Погонную массу берём из
 * справочника масс (/ext/profiles), а если его нет — по размерам сечения из
 * справочника проката калькулятора (площадь × 7850 кг/м³) с пометкой «Требует
 * проверки». Без того и другого строка получает «Нужен ввод массы».
 */
import type { RollMark } from '../types/api'
import type { Job, MassSource, OgzRow, RowStatus } from '../types/ogz'
import { buildRollIndex, markAliases } from './prefillMapper'

export interface OcrpdfColumn {
  index: number
  role: string
  element: string
  letter: string
  title: string
}

export interface OcrpdfRow {
  row: number
  kind: string
  position: number | null
  profile_group: string
  steel_grade: string
  standards: string[]
  profile_size: string | null
  elements: Record<string, number | null>
  total: number | null
  validation: string
  /** ГОСТ сортамента из колонки «Наименование профиля» (ocrpdf ≥ 2026-09-04). */
  profile_standards?: string[]
  /** ГОСТ стали из колонки «Марка металла». */
  steel_standards?: string[]
  /** Равновероятные прочтения марки, когда буква серии не разобрана («2011» → 20Б1/20Ш1/20К1). */
  profile_size_candidates?: string[]
}

/** Подпись вида профиля для таблицы формы ОГЗ. */
export const CATEGORY_LABELS: Record<string, string> = {
  balka: 'Двутавр',
  shveller: 'Швеллер',
  shveller_gnyt: 'Швеллер гнутый',
  ygolok: 'Уголок',
  ygolok_gnyt: 'Уголок гнутый',
  tryba_es_kvadr: 'Труба квадратная',
  tryba_es_pr: 'Труба прямоугольная',
  tryba_es_krug: 'Труба круглая',
  tryba_vgp: 'Труба ВГП',
  tavr: 'Тавр'
}

/** «Двутавр», «Уголок», «Лист» — по наименованию группы, ГОСТ и марке строки. */
export function profileFamilyLabel(row: Pick<OgzRow, 'name' | 'gostProfile' | 'profileRaw' | 'profileMark' | 'isSheet'>): string {
  if (row.isSheet) return 'Лист'
  const cat = profileCategory(row.name || '', row.gostProfile || '', row.profileRaw || row.profileMark || '')
  if (cat) return CATEGORY_LABELS[cat] || cat
  const name = String(row.name || '').trim()
  return name && name !== 'Элемент' ? name : ''
}

export interface OcrpdfTable {
  index: number
  title: string
  kind: string
  part: string
  page: number
  columns: OcrpdfColumn[]
  header_rows: number[]
  rows: OcrpdfRow[]
  checks?: { row: number; status: string }[]
}

export interface OcrpdfResult {
  type: 'ocrpdf:result'
  job: string
  filename: string
  report?: Record<string, unknown>
  tables: OcrpdfTable[]
}

export const OCR_RESULT_TYPE = 'ocrpdf:result'
export const STEEL_DENSITY_KG_M3 = 7850

export function isOcrpdfResult(x: unknown): x is OcrpdfResult {
  if (!x || typeof x !== 'object') return false
  const o = x as Record<string, unknown>
  return o.type === OCR_RESULT_TYPE && typeof o.job === 'string' && Array.isArray(o.tables)
}

/** Локальный id задания — по нему extApi понимает, что задание живёт в браузере. */
export const OCR_JOB_PREFIX = 'ocr-'

export function ocrJobId(ocrJob: string): string {
  return OCR_JOB_PREFIX + String(ocrJob || '').replace(/[^0-9a-f]/gi, '').slice(0, 12)
}

const SHEET_GROUP_RE = /лист|листов/i
const SHEET_SIZE_RE = /^(?:[δбd]\s*=\s*|t\s*|[-–—]\s*)?(\d+(?:[.,]\d+)?)\s*(?:мм|mm)?$/i

/** Толщина листа в мм из «δ=4 мм», «t8», «-6», «10 мм». */
export function sheetThicknessMm(size: string | null | undefined): number | null {
  const s = String(size || '').trim()
  if (!s) return null
  const m = SHEET_SIZE_RE.exec(s)
  if (!m) return null
  const v = Number(m[1].replace(',', '.'))
  return Number.isFinite(v) && v > 0 && v <= 200 ? v : null
}

export function isSheetRow(row: Pick<OcrpdfRow, 'profile_group' | 'profile_size'>): boolean {
  if (SHEET_GROUP_RE.test(row.profile_group || '')) return true
  const size = String(row.profile_size || '').trim()
  // «δ=4», «t40» — толщина листа: у профилей обозначение начинается с числа или серии
  return /^[δбd]\s*=/i.test(size) || /^t\s?\d/i.test(size)
}

/**
 * Служебная «группа» без размера: марка стали (в т.ч. прочитанная с ошибками),
 * голое число или надбавка в процентах. Такие строки — итоги по маркам стали
 * и допуски («масса наплавленного металла 1%»), а не позиции.
 */
export function isServiceGroup(group: string | null | undefined): boolean {
  const g = String(group || '').replace(/\s+/g, ' ').trim()
  if (!g) return true
  if (/^[СC€(\[]?\s?\d{3,4}[-–]?\d?$/i.test(g)) return true          // С255-5, 5553, С3556, 0663, €390
  if (/^\d+$/.test(g)) return true
  if (/%|наплав|неучт|неучёт|допуск на/i.test(g)) return true
  return false
}

/** Марка без символа типа профиля: «□140х5» → «140х5», «L 100х8» → «100х8», «Ι 20Б1» → «20Б1». */
/** Обозначение профиля, после которого одиночный символ может быть только значком типа. */
const TRAILING_GLYPH_DESIGNATION_RE =
  /^(?:\d{2,3}[БШКДМBWKDM]\d?|\d{1,3}(?:[.,]\d)?[хx×]\d{1,3}(?:[хx×]\d{1,2}(?:[.,]\d)?)?|\d{1,3}[ПпPp]а?|[tT]\s?\d{1,3}(?:[хx×]\d{1,3})?|RD\d{1,3})$/u

export function cleanMark(size: string | null | undefined): string {
  let s = String(size || '').trim()
  // «Гн.□100х5» / «Гн 100х5» — гнутый профиль: префикс не часть размера,
  // в справочнике квадратная труба записана как «100 x 5»
  s = s.replace(/^Гн\.?\s*/iu, '')
  s = s.replace(/^[□∟⌶ΙI|L\[\]]\s*(?=[\d])/u, '')
  s = s.replace(/^[□∟⌶]\s*/u, '')
  s = s.replace(/\s*(?:мм|mm)$/i, '')
  s = s.replace(/\s+/g, ' ').trim()
  // значок типа профиля, попавший ПОСЛЕ обозначения из текстового слоя
  // («25Б1 т», «25Б1 1», «25х3 □», «8П С»): снимаем, если остаток — обозначение
  const tail = /^(.+?\S)\s+[тТLlСC71IΙ□◻■⌶∟⌐\[]$/u.exec(s)
  if (tail && TRAILING_GLYPH_DESIGNATION_RE.test(tail[1])) s = tail[1]
  return s
}

/** Ключ справочника масс: как sortament.Normalize на бэкенде — верхний регистр,
 * без пробелов, латинские буквы серии → кириллица, любой знак умножения → «Х». */
export function handbookKey(mark: string): string {
  let s = cleanMark(mark).toUpperCase().replace(/\s+/g, '')
  s = s.replace(/[X×*]/g, 'Х').replace(/,/g, '.')
  const m = /^(\d+(?:\.\d+)?)([A-ZА-Я]+)(\d*)$/.exec(s)
  if (m) {
    const latin: Record<string, string> = { B: 'Б', P: 'П', Y: 'У', K: 'К', M: 'М', C: 'С', E: 'Е', D: 'Д', W: 'Ш' }
    let series = m[2].replace(/[BPYKMCEDW]/g, (c) => latin[c] || c)
    let num = m[3]
    // «25ШО»: нуль после буквы серии прочитан как «О» — серия всегда одна буква
    const o = /^([БШКДМ])([ОO]{1,2})$/.exec(series)
    if (o && !num) { series = o[1]; num = o[2].replace(/[ОO]/g, '0') }
    s = m[1] + series + num
  }
  return s
}

/**
 * Категория сортамента (слаги 23met, как sortament.Category на бэкенде): по
 * наименованию группы, затем по номеру ГОСТ, затем по букве серии марки.
 * Нужна, потому что размерная марка сама по себе неоднозначна: «100х8» — это и
 * квадратная труба (21,4 кг/м), и уголок (12,25 кг/м).
 */
export type ProfileCategory =
  | 'balka' | 'shveller' | 'shveller_gnyt' | 'ygolok' | 'ygolok_gnyt'
  | 'tryba_es_kvadr' | 'tryba_es_pr' | 'tryba_es_krug' | 'tryba_vgp' | 'tavr' | ''

const GOST_RULES: [ProfileCategory, string][] = [
  ['balka', '57837'], ['balka', '26020'], ['balka', '8239'], ['balka', 'асчм'],
  ['ygolok', '8509'], ['ygolok', '8510'], ['ygolok_gnyt', '19771'], ['ygolok_gnyt', '19772'],
  ['shveller', '8240'], ['shveller', '5267'], ['tryba_es_kvadr', '30245'], ['tryba_vgp', '3262']
]

/** «AхBхt» — три размера замкнутого гнутого профиля (любой знак умножения). */
const TUBE_DIMS_RE = /^(\d+(?:[.,]\d+)?)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)$/i

export function profileCategory(group: string, gost: string, mark: string): ProfileCategory {
  const n = String(group || '').toLowerCase()
  const has = (...w: string[]) => w.every((x) => n.includes(x))
  const any = (...w: string[]) => w.some((x) => n.includes(x))
  if (has('швеллер', 'гнут')) return 'shveller_gnyt'
  if ((has('уголок', 'гнут')) || has('уголки', 'гнут')) return 'ygolok_gnyt'
  if ((n.includes('квадрат') || n.includes('прямоуголь')) && any('гнут', 'замкн', 'профил', 'труб')) {
    // Группа ГОСТ 30245 обычно общая («квадратные и прямоугольные»), а OCR
    // может оставить одно слово. Форму решает сама марка: «140х140х4» —
    // квадратная, «140х100х4» — прямоугольная. Иначе квадратная труба в
    // «прямоугольной» группе не находилась: в справочнике она лежит как
    // tryba_es_kvadr/140Х4, а голая «140Х4» неоднозначна (есть и круглая).
    const dims = TUBE_DIMS_RE.exec(cleanMark(mark).replace(/^[DdДд](?=\d)/, ''))
    if (dims) return dims[1] === dims[2] ? 'tryba_es_kvadr' : 'tryba_es_pr'
    return n.includes('квадрат') ? 'tryba_es_kvadr' : 'tryba_es_pr'
  }
  if (n.includes('водогазопровод') || n.includes('вгп')) return 'tryba_vgp'
  if (any('двутавр', 'балк')) return 'balka'
  if (n.includes('швеллер')) return 'shveller'
  if (any('уголок', 'уголки', 'уголков')) return 'ygolok'
  // «тавр» — после «двутавр», иначе двутавры ушли бы в тавры
  if (any('тавр')) return 'tavr'
  // «Трубы стальные …» без уточнения формы — круглые (электросварные/бесшовные)
  if (n.includes('труб')) return 'tryba_es_krug'
  const g = String(gost || '').toLowerCase() + ' ' + n
  for (const [cat, code] of GOST_RULES) if (g.includes(code)) return cat
  const m = handbookKey(mark)
  if (/^\d+(?:\.\d+)?[БШКМД]\d*$/.test(m)) return 'balka'
  if (/^\d+(?:\.\d+)?[ПУЭ]$/.test(m)) return 'shveller'
  // «□140х5» / «∟100х8»: символ типа профиля в самой марке
  const raw = String(mark || '').trim()
  if (/^□/.test(raw)) return 'tryba_es_kvadr'
  if (/^[∟L]\s*\d/.test(raw)) return 'ygolok'
  return ''
}

/**
 * Варианты записи марки для поиска в справочнике проката. Уголок в
 * спецификации — «150х150х10», в справочнике — «150 x 10» (равнополочный) или
 * «150/100 x 10» (неравнополочный).
 */
export function rollMarkCandidates(category: ProfileCategory, mark: string): string[] {
  const clean = mark.trim().replace(/^[DdДд](?=\d)/, '')
  const out = [mark]
  if (clean !== mark.trim()) out.push(clean)
  const m = /^(\d+(?:[.,]\d+)?)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)$/i.exec(clean)
  if (m && (category === 'ygolok' || category === 'ygolok_gnyt')) {
    out.push(m[1] === m[2] ? `${m[1]}х${m[3]}` : `${m[1]}/${m[2]}х${m[3]}`)
  }
  if (m && (category === 'tryba_es_kvadr' || category === 'tryba_es_pr') && m[1] === m[2]) {
    out.push(`${m[1]}х${m[3]}`)   // квадратная труба в сортаменте — «200 x 7»
  }
  return out
}

/** Название колонки «масса по элементам»: служебные «col4» (шапка не распознана) — пусто. */
export function constructionName(key: string): string {
  const s = String(key || '').trim()
  return /^col\d+$/i.test(s) ? '' : s
}

/** Формы справочника проката калькулятора, совместимые с категорией. */
export const SHAPES_BY_CATEGORY: Record<string, string[]> = {
  balka: ['I-beam_', 'I-beam_sm', 'I-beam_sl'],
  shveller: ['channel_', 'channel_sl'],
  shveller_gnyt: ['channel_', 'channel_sl'],
  ygolok: ['corner_', 'corner_e', 'corner_ue'],
  ygolok_gnyt: ['corner_', 'corner_e', 'corner_ue'],
  tryba_es_kvadr: ['tube_sq'],
  tryba_es_pr: ['profile_', 'profile_sm'],
  tryba_es_krug: ['tube_', 'tube_sm'],
  tryba_vgp: ['tube_', 'tube_sm'],
  tavr: ['brands_', 'brands_sm']
}

/** Форма сечения по умолчанию для категории — когда марка не найдена в справочнике проката. */
export function defaultShapeFor(category: ProfileCategory): string | undefined {
  const shapes = SHAPES_BY_CATEGORY[category]
  return shapes ? shapes[0] : undefined
}

/**
 * Марка в записи справочника масс. Равнополочный уголок в спецификации пишут
 * «L 100х8», а в справочнике — «100Х100Х8».
 */
export function handbookMarkFor(category: ProfileCategory, mark: string): string {
  const key = handbookKey(mark).replace(/^[DdДд](?=\d)/, '')
  if ((category === 'ygolok' || category === 'ygolok_gnyt')) {
    const m = /^(\d+(?:\.\d+)?)Х(\d+(?:\.\d+)?)$/.exec(key)
    if (m) return `${m[1]}Х${m[1]}Х${m[2]}`
  }
  if (category === 'tryba_es_kvadr' || category === 'tryba_es_pr') {
    // квадратная труба «200х200х7» в справочнике — «200Х7»
    const m = /^(\d+(?:\.\d+)?)Х(\d+(?:\.\d+)?)Х(\d+(?:\.\d+)?)$/.exec(key)
    if (m && m[1] === m[2]) return `${m[1]}Х${m[3]}`
  }
  return key
}

/** Ключи карты справочника масс: «категория/марка» и, для однозначных марок, «марка». */
export function lookupHandbook(handbook: Map<string, number> | undefined, category: ProfileCategory, mark: string): number | undefined {
  if (!handbook) return undefined
  const hm = handbookMarkFor(category, mark)
  if (category) {
    const v = handbook.get(`${category}/${hm}`)
    if (v) return v
    // квадратные и прямоугольные трубы — один ГОСТ и одна группа в
    // спецификации; ключи не пересекаются («140Х4» и «140Х100Х4»)
    const twin = category === 'tryba_es_pr' ? 'tryba_es_kvadr' : category === 'tryba_es_kvadr' ? 'tryba_es_pr' : ''
    if (twin) {
      const w = handbook.get(`${twin}/${hm}`)
      if (w) return w
    }
  }
  return handbook.get(hm)
}

/** Площадь сечения, мм², по размерам из справочника проката калькулятора. */
export function sectionAreaMm2(shape: string, dims: Record<string, number> | undefined): number | null {
  if (!dims) return null
  const d = (k: string) => (Number.isFinite(dims[k]) ? Number(dims[k]) : 0)
  const fillet = (R: number, n: number) => (R > 0 ? n * (1 - Math.PI / 4) * R * R : 0)
  if (shape.startsWith('I-beam') || shape.startsWith('channel')) {
    const h = d('h'), b = d('b'), s = d('s'), t = d('t'), R = d('R')
    if (!(h > 0 && b > 0 && s > 0 && t > 0)) return null
    return 2 * b * t + (h - 2 * t) * s + fillet(R, shape.startsWith('I-beam') ? 4 : 2)
  }
  if (shape === 'corner_e' || shape === 'corner_') {
    const b = d('b'), t = d('t'), R = d('R'), r = d('r')
    if (!(b > 0 && t > 0)) return null
    return (2 * b - t) * t + fillet(R, 1) - fillet(r, 2)
  }
  if (shape === 'corner_ue') {
    const B = d('B'), b = d('b'), t = d('t')
    if (!(B > 0 && b > 0 && t > 0)) return null
    return (B + b - t) * t
  }
  if (shape === 'tube_sq') {
    const A = d('A'), s = d('s')
    if (!(A > 0 && s > 0 && 2 * s < A)) return null
    return 4 * (A - s) * s - (4 - Math.PI) * 3 * s * s
  }
  if (shape.startsWith('profile')) {
    const h = d('h'), b = d('b'), t = d('t')
    if (!(h > 0 && b > 0 && t > 0)) return null
    return 2 * (h + b - 2 * t) * t - (4 - Math.PI) * 3 * t * t
  }
  if (shape === 'tube_sm' || shape === 'tube_') {
    const dia = d('d'), wall = d('h') || d('s') || d('t')
    if (!(dia > 0 && wall > 0 && 2 * wall < dia)) return null
    return Math.PI * (dia - wall) * wall
  }
  return null
}

/**
 * Только точное совпадение марки со справочником проката. Мягкий поиск по
 * подстроке из prefillMapper.matchRoll здесь опасен: «140х5» содержит «40х5»,
 * и труба 140×5 получала бы массу трубы 40×5 (4,99 кг/м вместо 20,9).
 */
export function matchRollExact(mark: string, index: Map<string, RollMark> | undefined): RollMark | null {
  if (!index) return null
  for (const a of markAliases(mark)) {
    const hit = index.get(a)
    if (hit) return hit
  }
  return null
}

export function massPerMeterFromDims(shape: string, dims: Record<string, number> | undefined): number | null {
  const a = sectionAreaMm2(shape, dims)
  if (!a || a <= 0) return null
  return Math.round((a / 1e6) * STEEL_DENSITY_KG_M3 * 100) / 100
}

/** Диаметр круглого профиля из марки («RD18», «Ø 18», «⌀18», «d18»), мм; 0 — не круг. */
export function roundBarDiameterMm(mark: string, group: string | null | undefined): number {
  const m = /^(?:RD|Ø|⌀|∅|d|D)\s?(\d{1,3}(?:[.,]\d)?)$/u.exec(String(mark || '').trim())
  if (!m) return 0
  const n = String(group || '').toLowerCase()
  // «RD18» однозначен и без наименования; голое «d18» — только в группе кругов
  if (!/^RD/i.test(m[0]) && !/^[Ø⌀∅]/u.test(m[0]) && !/круг/.test(n)) return 0
  return Number(m[1].replace(',', '.'))
}

/** Погонная масса круглого профиля, кг/м. */
export function roundBarMassPerMeter(diameterMm: number): number {
  const areaMm2 = Math.PI * diameterMm * diameterMm / 4
  return Math.round((areaMm2 / 1e6) * STEEL_DENSITY_KG_M3 * 100) / 100
}

/**
 * Погонная масса уголка по размерам из самой марки, кг/м — когда марки нет ни
 * в справочнике масс, ни в справочнике проката (серия отсутствует или профиль
 * нестандартный, как «180х180х15»). Площадь без учёта закруглений:
 * равнополочный t·(2b − t), неравнополочный t·(B + b − t); занижение против
 * ГОСТ около 1 %, поэтому строка идёт с пометкой «Требует проверки».
 * Для гнутых уголков (без закруглений) формула точная. 0 — марка не уголок.
 */
export function angleMassPerMeterFromMark(category: ProfileCategory, mark: string): number {
  if (category !== 'ygolok' && category !== 'ygolok_gnyt') return 0
  const s = cleanMark(mark).replace(/,/g, '.')
  const m3 = /^(\d+(?:\.\d+)?)\s*[хx×*]\s*(\d+(?:\.\d+)?)\s*[хx×*]\s*(\d+(?:\.\d+)?)$/i.exec(s)
  const m2 = m3 ? null : /^(\d+(?:\.\d+)?)\s*[хx×*]\s*(\d+(?:\.\d+)?)$/i.exec(s)
  let B: number, b: number, t: number
  if (m3) [B, b, t] = [Number(m3[1]), Number(m3[2]), Number(m3[3])]
  else if (m2) [B, b, t] = [Number(m2[1]), Number(m2[1]), Number(m2[2])]
  else return 0
  // толщина всегда меньше полок, полки — от 20 до 250 мм: иначе это не уголок
  if (!(t > 0 && t < Math.min(B, b) && B >= 20 && b >= 20 && B <= 250 && b <= 250)) return 0
  const areaMm2 = t * (B + b - t)
  return Math.round((areaMm2 / 1e6) * STEEL_DENSITY_KG_M3 * 100) / 100
}

/** Погонная масса листа, кг/м² (для строк листового проката). */
export function sheetMassPerM2(thicknessMm: number): number {
  return Math.round(thicknessMm * STEEL_DENSITY_KG_M3 / 1000 * 100) / 100
}

export interface BuildOptions {
  /** Справочник проката калькулятора — для подбора сечения и массы по размерам. */
  roll?: RollMark[]
  /** Справочник масс (/ext/profiles): ключ handbookKey(mark) → кг/м. */
  handbook?: Map<string, number>
  now?: string
}

export interface BuildResult {
  job: Job
  /** Строки-итоги, шапки и пустые строки, пропущенные при импорте. */
  skipped: number
  notes: string[]
}

function shortGroup(group: string): string {
  // первая строка наименования без номера ГОСТ: «Профиль стальной гнутый … ГОСТ 30245-2012»
  const s = String(group || '').replace(/\s+/g, ' ').trim()
  // \b не знает кириллицы — границу слова ищем пробелом
  const m = /(?:^|\s)(ГОСТ|СТО|ТУ|EN|DIN)(?=\s|$)/i.exec(s)
  const cut = m ? m.index : -1
  return (cut > 0 ? s.slice(0, cut) : s).trim() || 'Элемент'
}

function tableHasSpec(t: OcrpdfTable): boolean {
  if (t.kind === 'spec_main') return true
  const roles = new Set((t.columns || []).map((c) => c.role))
  return roles.has('profile_size') && (roles.has('element_mass') || roles.has('total_mass'))
}

function round2(v: number): number {
  return Math.round(v * 100) / 100
}

/**
 * Погонная масса марки: справочник масс → справочник проката (по размерам
 * сечения, только среди форм своей категории) → круглый профиль по диаметру.
 */
export function resolveMassPerMeter(
  mark: string,
  category: ProfileCategory,
  group: string,
  handbook: Map<string, number> | undefined,
  roll: RollMark[],
  index: Map<string, RollMark> | undefined
): { mpm: number | null; source: MassSource | '' } {
  const hb = lookupHandbook(handbook, category, mark)
  if (hb && hb > 0) return { mpm: hb, source: 'cache' }
  if (roll.length) {
    // сечение ищем только среди форм своей категории: «100х8» есть и у
    // труб, и у уголков
    const shapes = SHAPES_BY_CATEGORY[category]
    const pool = shapes ? roll.filter((x) => shapes.includes(x.shape)) : roll
    const idx = pool.length ? (shapes ? buildRollIndex(pool) : index) : undefined
    let hit: RollMark | null = null
    for (const cand of rollMarkCandidates(category, mark)) {
      hit = matchRollExact(cand, idx)
      if (hit) break
    }
    if (hit) {
      const mpm = massPerMeterFromDims(hit.shape, hit.dims)
      if (mpm) return { mpm, source: 'formula' }
    }
  }
  // круглый профиль по диаметру («RD18», «Ø18», «⌀18»): в справочнике
  // проката его нет, масса 1 м считается по площади круга
  const rd = roundBarDiameterMm(mark, group)
  if (rd) return { mpm: roundBarMassPerMeter(rd), source: 'formula' }
  // уголок, которого нет в словарях: по размерам полок и толщины из марки
  const ang = angleMassPerMeterFromMark(category, mark)
  if (ang) return { mpm: ang, source: 'formula' }
  return { mpm: null, source: '' }
}

/** Собирает задание ОГЗ из результата OCR. Массы в спецификации — в тоннах. */
export function buildJobFromOcr(res: OcrpdfResult, opts: BuildOptions = {}): BuildResult {
  const now = opts.now || new Date().toISOString()
  const roll = opts.roll || []
  const index = roll.length ? buildRollIndex(roll) : undefined
  const handbook = opts.handbook
  const profileRows: OgzRow[] = []
  const sheetRows: OgzRow[] = []
  const notes: string[] = []
  let skipped = 0
  let nextId = 1
  let autoMarks = 0   // марка подобрана из вариантов OCR по справочнику
  let askMarks = 0    // вариантов несколько или ни одного — выбор за пользователем
  let carriedGroups = 0 // наименование группы взято со строки выше

  for (const t of res.tables || []) {
    // «В том числе по маркам или наименованиям» — разбивка итогов по маркам
    // стали, не профили: те же массы попали бы в форму второй раз.
    if (t.kind === 'unreadable' || t.kind === 'mass_by_grade' || !tableHasSpec(t)) continue
    const failedRows = new Set((t.checks || []).filter((c) => c.status === 'failed').map((c) => c.row))
    // Наименование группы в спецификации пишут один раз на первую позицию, а у
    // следующих строк той же группы графа пустая (file-13: «Уголки … ГОСТ
    // 8509-93» у поз. 14, у поз. 15 «180х180х15» — пусто). Merged-ячейки конвейер
    // протягивает сам, а отдельную пустую клетку — нет; здесь группа и ГОСТ
    // переносятся со строки выше до ближайшей строки-итога.
    let carried: { group: string; standards: string[] } | null = null
    for (const raw of t.rows || []) {
      if (raw.kind !== 'data') { carried = null; skipped++; continue }
      let r = raw
      let groupCarried = false
      if (!isServiceGroup(raw.profile_group)) {
        carried = {
          group: raw.profile_group,
          standards: raw.profile_standards !== undefined ? raw.profile_standards : (raw.standards || [])
        }
      } else if (carried && !String(raw.profile_group || '').trim() && String(raw.profile_size || '').trim()) {
        r = { ...raw, profile_group: carried.group, profile_standards: carried.standards }
        groupCarried = true
        carriedGroups++
      }
      const masses: { construction: string; tonnes: number }[] = []
      for (const [key, v] of Object.entries(r.elements || {})) {
        if (typeof v === 'number' && Number.isFinite(v) && v > 0) {
          masses.push({ construction: constructionName(key), tonnes: v })
        }
      }
      if (!masses.length && typeof r.total === 'number' && r.total > 0) {
        masses.push({ construction: '', tonnes: r.total })
      }
      if (!masses.length) { skipped++; continue }

      const uncertain = r.validation === 'failed' || failedRows.has(r.row) || groupCarried
      const sheet = isSheetRow(r)
      const mark = cleanMark(r.profile_size)
      // Строка без размера — не позиция спецификации, если вместо группы стоит
      // марка стали («С255-5», OCR-варианты «5553», «С3556», «0663», «€390»),
      // просто число, либо надбавка в процентах («масса наплавленного металла
      // 1%», «неучтённый металл 2%»). Это итоги по маркам и допуски, в
      // калькулятор они не идут.
      if (!mark && !sheet && isServiceGroup(raw.profile_group)) { skipped++; continue }
      // ГОСТ профиля — только из колонки «Наименование профиля». ГОСТ марки
      // стали (27772) сюда не подставляем даже когда свой не прочитался:
      // это стандарт стали, а не сортамента, и он ломает подбор по справочнику.
      // Единственное поле `standards` — формат старого ocrpdf без разделения.
      const gost = r.profile_standards !== undefined
        ? (r.profile_standards[0] || '')
        : ((r.standards && r.standards[0]) || '')
      const groupName = shortGroup(r.profile_group)

      for (const m of masses) {
        const massKg = round2(m.tonnes * 1000)
        const base: OgzRow = {
          id: nextId++,
          name: groupName,
          profileMark: mark,
          profileRaw: String(r.profile_size || ''),
          gostProfile: gost,
          steelGrade: String(r.steel_grade || '').split('\n')[0].trim(),
          ppNumber: r.position == null ? '' : String(r.position),
          construction: m.construction,
          mass: massKg,
          massUnit: 'kg',
          massPerMeter: 0,
          massSource: '',
          sourceUrl: '',
          isSheet: sheet,
          lengthM: 0,
          areaM2: 0,
          classification: 'учитывается',
          status: 'Нужен ввод массы',
          heatingSides: '4',
          fireLimit: '',
          bearingType: '',
          coatingType: ''
        }
        if (sheet) {
          const th = sheetThicknessMm(r.profile_size)
          if (th) {
            base.massPerMeter = sheetMassPerM2(th)
            base.areaM2 = round2(massKg / base.massPerMeter)
            base.massSource = 'formula'
            base.status = uncertain ? 'Требует проверки' : 'Посчитано'
          } else {
            base.status = 'Нет данных'
          }
          sheetRows.push(base)
          continue
        }
        const category = profileCategory(r.profile_group, gost, String(r.profile_size || ''))
        let { mpm, source } = resolveMassPerMeter(mark, category, r.profile_group, handbook, roll, index)
        let markUncertain = false
        // OCR не разобрал букву серии («2011»): пробуем варианты по справочнику.
        // Единственный найденный — подставляем с пометкой «Требует проверки»;
        // несколько или ни одного — оставляем выбор пользователю в таблице.
        const rawCands = [...new Set((r.profile_size_candidates || []).map((c) => cleanMark(c)).filter(Boolean))]
        if (!mpm && rawCands.length) {
          const resolved = rawCands.map((c) => ({
            mark: c,
            ...resolveMassPerMeter(c, category, r.profile_group, handbook, roll, index)
          }))
          const found = resolved.filter((c) => c.mpm && c.mpm > 0)
          if (found.length === 1) {
            base.profileMark = found[0].mark
            mpm = found[0].mpm
            source = found[0].source
            markUncertain = true
            autoMarks++
          } else {
            base.profileCandidates = (found.length ? found : resolved).map((c) => ({
              mark: c.mark,
              massPerMeter: c.mpm || 0,
              source: c.source
            }))
            askMarks++
          }
        }
        if (mpm && mpm > 0) {
          base.massPerMeter = mpm
          base.massSource = source
          base.lengthM = round2(massKg / mpm)
          const status: RowStatus =
            source === 'formula' || uncertain || markUncertain ? 'Требует проверки' : 'Посчитано'
          base.status = status
        }
        profileRows.push(base)
      }
    }
  }

  if (!profileRows.length && !sheetRows.length) {
    notes.push('В распознанных таблицах нет строк спецификации с массами.')
  }
  const formula = profileRows.filter((r) => r.massSource === 'formula').length
  if (formula) {
    notes.push(`Погонная масса ${formula} строк(и) посчитана по размерам сечения — проверьте длину.`)
  }
  const manual = profileRows.filter((r) => r.status === 'Нужен ввод массы').length
  if (manual) {
    notes.push(`Для ${manual} строк(и) профиль не найден в справочнике — введите массу 1 м вручную.`)
  }
  if (autoMarks) {
    notes.push(`Марка ${autoMarks} строк(и) подобрана по справочнику из вариантов OCR (буква серии не читалась) — проверьте.`)
  }
  if (askMarks) {
    notes.push(`У ${askMarks} строк(и) OCR не разобрал букву серии двутавра — выберите марку из вариантов в таблице.`)
  }
  if (carriedGroups) {
    notes.push(`У ${carriedGroups} строк(и) наименование профиля взято со строки выше (графа в спецификации пустая) — проверьте вид профиля.`)
  }

  const job: Job = {
    id: ocrJobId(res.job),
    status: 'ready',
    confirmed: false,
    createdAt: now,
    updatedAt: now,
    profileRows,
    sheetRows
  }
  return { job, skipped, notes }
}
