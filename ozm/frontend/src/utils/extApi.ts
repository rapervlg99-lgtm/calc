import { api } from './api'
import { createDemoJob, DEMO_JOB_ID, demoPrefill } from '../fixtures/demoJob'
import type { Job, OgzRow, OgzRowPatch, PrefillPayload } from '../types/ogz'
import { handbookKey, OCR_JOB_PREFIX } from './ocrImport'

// Bearer для /ext и /calc выставляет общий интерцептор в ./api.ts

/**
 * Задания, живущие в браузере, а не на сервере: демо-форма и задания,
 * собранные из результата локального OCR (см. ocrImport.ts). Для них все
 * операции /ext выполняются в памяти; OCR-задания дублируются в sessionStorage,
 * чтобы переживать перезагрузку страницы формы.
 */
const localJobs = new Map<string, Job>()
const LOCAL_KEY = 'ozm-local-job:'

function ensureDemoJob(): Job {
  let job = localJobs.get(DEMO_JOB_ID)
  if (!job) {
    job = createDemoJob()
    localJobs.set(DEMO_JOB_ID, job)
  }
  return job
}

export function resetDemoJob(): void {
  localJobs.set(DEMO_JOB_ID, createDemoJob())
}

export function isLocalJob(id: string): boolean {
  return id === DEMO_JOB_ID || id.startsWith(OCR_JOB_PREFIX)
}

function persistLocalJob(job: Job): void {
  if (job.id === DEMO_JOB_ID) return
  try {
    sessionStorage.setItem(LOCAL_KEY + job.id, JSON.stringify(job))
  } catch {
    /* ignore quota */
  }
}

export function registerLocalJob(job: Job): void {
  localJobs.set(job.id, job)
  persistLocalJob(job)
}

function localJob(id: string): Job {
  if (id === DEMO_JOB_ID) return ensureDemoJob()
  let job = localJobs.get(id)
  if (!job) {
    try {
      const raw = sessionStorage.getItem(LOCAL_KEY + id)
      if (raw) {
        job = JSON.parse(raw) as Job
        localJobs.set(id, job)
      }
    } catch {
      /* ignore */
    }
  }
  if (!job) throw new Error(`local job ${id} not found`)
  return job
}

function touch(job: Job): void {
  job.updatedAt = new Date().toISOString()
  persistLocalJob(job)
}

export async function createExtJob(file: File): Promise<{ id: string; status: string }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<{ id: string; status: string }>('/ext/jobs', form)
  return data
}

export async function getExtJob(id: string): Promise<Job> {
  if (isLocalJob(id)) return structuredClone(localJob(id))
  const { data } = await api.get<Job>(`/ext/jobs/${id}`)
  return data
}

export async function patchExtRow(jobId: string, rowId: number, patch: OgzRowPatch): Promise<OgzRow> {
  if (isLocalJob(jobId)) {
    const job = localJob(jobId)
    const list = [...job.profileRows, ...job.sheetRows]
    const row = list.find((r) => r.id === rowId)
    if (!row) throw new Error(`local row ${rowId} not found`)
    Object.assign(row, patch)
    // Как ogzform.Recompute на сервере: ввели массу 1 м — пересчитали длину.
    if (patch.massPerMeter && patch.massPerMeter > 0 && patch.lengthM == null && row.mass > 0) {
      row.lengthM = Math.round((row.mass / patch.massPerMeter) * 100) / 100
      row.massSource = 'manual'
      if (row.status === 'Нужен ввод массы' || row.status === 'Нет данных') {
        row.status = 'Посчитано'
      }
    }
    touch(job)
    return structuredClone(row)
  }
  const { data } = await api.patch<OgzRow>(`/ext/jobs/${jobId}/rows/${rowId}`, patch)
  return data
}

function nextLocalRowId(job: Job): number {
  const ids = [...job.profileRows, ...job.sheetRows].map((r) => r.id)
  return (ids.length ? Math.max(...ids) : 0) + 1
}

export async function createExtRow(jobId: string): Promise<OgzRow> {
  if (isLocalJob(jobId)) {
    const job = localJob(jobId)
    const row: OgzRow = {
      id: nextLocalRowId(job),
      name: 'Элемент',
      profileMark: '',
      profileRaw: '',
      gostProfile: '',
      steelGrade: '',
      ppNumber: '',
      construction: 'Балки',
      mass: 0,
      massUnit: 'kg',
      massPerMeter: 0,
      massSource: '',
      sourceUrl: '',
      isSheet: false,
      lengthM: 1,
      areaM2: 0,
      classification: 'учитывается',
      status: 'Нужен ввод массы',
      heatingSides: '4',
      fireLimit: '',
      bearingType: '',
      coatingType: ''
    }
    job.profileRows.push(row)
    touch(job)
    return structuredClone(row)
  }
  const { data } = await api.post<OgzRow>(`/ext/jobs/${jobId}/rows`)
  return data
}

export async function copyExtRow(jobId: string, rowId: number): Promise<OgzRow> {
  if (isLocalJob(jobId)) {
    const job = localJob(jobId)
    const list = rowIsSheet(job, rowId) ? job.sheetRows : job.profileRows
    const src = list.find((r) => r.id === rowId)
    if (!src) throw new Error(`local row ${rowId} not found`)
    const copy: OgzRow = { ...structuredClone(src), id: nextLocalRowId(job) }
    const idx = list.findIndex((r) => r.id === rowId)
    list.splice(idx + 1, 0, copy)
    touch(job)
    return structuredClone(copy)
  }
  const { data } = await api.post<OgzRow>(`/ext/jobs/${jobId}/rows/${rowId}/copy`)
  return data
}

export async function deleteExtRow(jobId: string, rowId: number): Promise<void> {
  if (isLocalJob(jobId)) {
    const job = localJob(jobId)
    const drop = (rows: OgzRow[]) => {
      const i = rows.findIndex((r) => r.id === rowId)
      if (i !== -1) rows.splice(i, 1)
    }
    drop(job.profileRows)
    drop(job.sheetRows)
    touch(job)
    return
  }
  await api.delete(`/ext/jobs/${jobId}/rows/${rowId}`)
}

function rowIsSheet(job: Job, rowId: number): boolean {
  return job.sheetRows.some((r) => r.id === rowId)
}

export async function confirmExtJob(id: string): Promise<void> {
  if (isLocalJob(id)) {
    const job = localJob(id)
    job.confirmed = true
    job.confirmedAt = new Date().toISOString()
    job.updatedAt = job.confirmedAt
    persistLocalJob(job)
    return
  }
  await api.post(`/ext/jobs/${id}/confirm`)
}

export async function getExtPrefill(id: string): Promise<PrefillPayload> {
  if (isLocalJob(id)) return demoPrefill(localJob(id))
  const { data } = await api.get<PrefillPayload>(`/ext/jobs/${id}/prefill`)
  return data
}

/**
 * Справочник масс профилей (кг/м) с сервера. Ключи карты: «категория/марка»
 * для записей с категорией 23met и «марка» — только если марка однозначна
 * (не встречается в нескольких категориях). Если /ext недоступен (OCR выключен
 * флагом) — пустая карта, импорт из OCR посчитает массу по размерам сечения.
 */
export interface ProfileCatalogItem {
  mark: string
  massPerMeter: number
  category?: string
}

let catalogPromise: Promise<ProfileCatalogItem[]> | null = null

/**
 * Плоский список справочника масс (/ext/profiles): марка, категория, кг/м.
 * Грузится один раз на сессию — по нему строятся подсказки при ручном вводе
 * марки и карта fetchMassHandbook. Если /ext недоступен — пустой список.
 */
export function fetchProfileCatalog(): Promise<ProfileCatalogItem[]> {
  if (!catalogPromise) {
    catalogPromise = api
      .get<ProfileCatalogItem[]>('/ext/profiles', { timeout: 15000 })
      .then(({ data }) => (Array.isArray(data) ? data : []))
      .catch(() => {
        catalogPromise = null // в следующий раз попробуем снова
        return [] as ProfileCatalogItem[]
      })
  }
  return catalogPromise
}

export async function fetchMassHandbook(): Promise<Map<string, number>> {
  const out = new Map<string, number>()
  try {
    const data = await fetchProfileCatalog()
    const cats = new Map<string, Set<string>>()
    for (const p of data || []) {
      const key = handbookKey(p.mark)
      if (!key || !(p.massPerMeter > 0)) continue
      const cat = String(p.category || '')
      if (cat && !out.has(`${cat}/${key}`)) out.set(`${cat}/${key}`, p.massPerMeter)
      if (!cats.has(key)) cats.set(key, new Set())
      cats.get(key)!.add(cat)
      if (!out.has(key)) out.set(key, p.massPerMeter)
    }
    for (const [key, set] of cats) {
      if (set.size > 1) out.delete(key) // неоднозначная марка — только с категорией
    }
  } catch {
    /* справочника нет — считаем по размерам */
  }
  return out
}

export { DEMO_JOB_ID }
