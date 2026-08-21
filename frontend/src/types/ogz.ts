// OCR /ext types — mirror backend openapi-ext.yaml

export type RowStatus =
  | 'Посчитано'
  | 'Не считается'
  | 'Требует проверки'
  | 'Нужен ввод массы'
  | 'Нет данных'

export type JobStatus = 'pending' | 'processing' | 'ready' | 'failed'
export type MassSource = '23met' | 'manual' | 'cache' | 'formula'

export interface OgzRow {
  id: number
  name: string
  profileMark: string
  profileRaw: string
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
