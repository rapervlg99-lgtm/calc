// OCR /ext types — mirror backend openapi-ext.yaml

export type RowStatus =
  | 'Посчитано'
  | 'Не считается'
  | 'Требует проверки'
  | 'Нужен ввод массы'
  | 'Нет данных'

export type JobStatus = 'pending' | 'processing' | 'ready' | 'failed'
export type MassSource = '23met' | 'manual' | 'cache' | 'formula'

/**
 * Вариант марки, когда OCR не разобрал букву серии («2011» → 20Б1 / 20Ш1 / 20К1).
 * massPerMeter — по справочнику, 0 если марки в справочнике нет.
 */
export interface ProfileCandidate {
  mark: string
  massPerMeter: number
  source: MassSource | ''
}

export interface OgzRow {
  id: number
  name: string
  profileMark: string
  profileRaw: string
  /** Клиентское поле: варианты марки для выбора пользователем (только у строк из OCR). */
  profileCandidates?: ProfileCandidate[]
  gostProfile: string
  steelGrade: string
  ppNumber: string
  construction: string
  mass: number
  massUnit: 'kg' | 't'
  massPerMeter: number
  massSource: MassSource | ''
  sourceUrl: string
  isSheet: boolean
  lengthM: number
  areaM2: number
  classification: string
  status: RowStatus
  heatingSides: string
  fireLimit: string
  bearingType: string
  coatingType: string
}

export interface Job {
  id: string
  status: JobStatus
  confirmed: boolean
  confirmedAt?: string
  createdAt: string
  updatedAt: string
  profileRows: OgzRow[]
  sheetRows: OgzRow[]
}

export interface OgzRowPatch {
  profileMark?: string
  profileCandidates?: ProfileCandidate[]
  massSource?: MassSource | ''
  massPerMeter?: number
  lengthM?: number
  classification?: string
  status?: RowStatus
  heatingSides?: string
  fireLimit?: string
  bearingType?: string
  coatingType?: string
  construction?: string
  name?: string
  /**
   * Клиентское поле: ГОСТ сортамента при смене вида профиля вручную
   * (двутавр → швеллер). В контракте /ext его нет — сервер поле игнорирует,
   * для заданий из локального OCR оно применяется в браузере.
   */
  gostProfile?: string
}

export interface PrefillItem {
  profileMark: string
  /** OCR construction column (Балки, Ригели, …) — used for element title. */
  construction?: string
  lengthM: number
  heatingSides: string
  fireLimit: string
  bearingType: string
  coatingType: string
  /** Client-enriched: ogz row id for group membership mapping. */
  rowId?: number
  /**
   * Client-enriched: формы справочника проката, среди которых искать марку
   * («140х5» есть и у квадратной, и у круглой трубы — категорию знает только
   * строка спецификации). Пусто — искать по всему справочнику.
   */
  shapes?: string[]
}

/** Client-enriched: element groups from the OCR form table. */
export interface PrefillGroup {
  title: string
  rowIds: number[]
}

export interface PrefillPayload {
  version: string
  jobId: string
  items: PrefillItem[]
  sheet: { areaM2: number }
  /** Client-enriched from ProfileRowsTable «Группа элементов». */
  groups?: PrefillGroup[]
}
