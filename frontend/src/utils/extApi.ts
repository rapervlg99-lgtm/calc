import { api } from './api'
import { createDemoJob, DEMO_JOB_ID, demoPrefill } from '../fixtures/demoJob'
import type { Job, OgzRow, OgzRowPatch, PrefillPayload } from '../types/ogz'

const DEV_TOKEN = import.meta.env.VITE_AUTH_DEV_TOKEN || 'dev-token'

/** Ensure Bearer for /ext (AUTH_DEV_MODE on backend). */
api.interceptors.request.use((cfg) => {
  if (!cfg.headers.Authorization) {
    cfg.headers.Authorization = `Bearer ${DEV_TOKEN}`
  }
  return cfg
})

let demoJob: Job | null = null

function ensureDemoJob(): Job {
  if (!demoJob) demoJob = createDemoJob()
  return demoJob
}

function isDemo(id: string): boolean {
  return id === DEMO_JOB_ID
}

export function resetDemoJob(): void {
  demoJob = createDemoJob()
}

export async function createExtJob(file: File): Promise<{ id: string; status: string }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<{ id: string; status: string }>('/ext/jobs', form)
  return data
}

export async function getExtJob(id: string): Promise<Job> {
  if (isDemo(id)) return structuredClone(ensureDemoJob())
  const { data } = await api.get<Job>(`/ext/jobs/${id}`)
  return data
}

export async function patchExtRow(jobId: string, rowId: number, patch: OgzRowPatch): Promise<OgzRow> {
  if (isDemo(jobId)) {
    const job = ensureDemoJob()
    const list = [...job.profileRows, ...job.sheetRows]
    const row = list.find((r) => r.id === rowId)
    if (!row) throw new Error(`demo row ${rowId} not found`)
    Object.assign(row, patch)
    job.updatedAt = new Date().toISOString()
    return structuredClone(row)
  }
  const { data } = await api.patch<OgzRow>(`/ext/jobs/${jobId}/rows/${rowId}`, patch)
  return data
}

function nextDemoRowId(job: Job): number {
  const ids = [...job.profileRows, ...job.sheetRows].map((r) => r.id)
  return (ids.length ? Math.max(...ids) : 0) + 1
}

export async function createExtRow(jobId: string): Promise<OgzRow> {
  if (isDemo(jobId)) {
    const job = ensureDemoJob()
    const row: OgzRow = {
      id: nextDemoRowId(job),
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
    job.updatedAt = new Date().toISOString()
    return structuredClone(row)
  }
  const { data } = await api.post<OgzRow>(`/ext/jobs/${jobId}/rows`)
  return data
}

export async function copyExtRow(jobId: string, rowId: number): Promise<OgzRow> {
  if (isDemo(jobId)) {
    const job = ensureDemoJob()
    const list = rowIsSheet(job, rowId) ? job.sheetRows : job.profileRows
    const src = list.find((r) => r.id === rowId)
    if (!src) throw new Error(`demo row ${rowId} not found`)
    const copy: OgzRow = { ...structuredClone(src), id: nextDemoRowId(job) }
    const idx = list.findIndex((r) => r.id === rowId)
    list.splice(idx + 1, 0, copy)
    job.updatedAt = new Date().toISOString()
    return structuredClone(copy)
  }
  const { data } = await api.post<OgzRow>(`/ext/jobs/${jobId}/rows/${rowId}/copy`)
  return data
}

export async function deleteExtRow(jobId: string, rowId: number): Promise<void> {
  if (isDemo(jobId)) {
    const job = ensureDemoJob()
    const drop = (rows: OgzRow[]) => {
      const i = rows.findIndex((r) => r.id === rowId)
      if (i !== -1) rows.splice(i, 1)
    }
    drop(job.profileRows)
    drop(job.sheetRows)
    job.updatedAt = new Date().toISOString()
    return
  }
  await api.delete(`/ext/jobs/${jobId}/rows/${rowId}`)
}

function rowIsSheet(job: Job, rowId: number): boolean {
  return job.sheetRows.some((r) => r.id === rowId)
}

export async function confirmExtJob(id: string): Promise<void> {
  if (isDemo(id)) {
    const job = ensureDemoJob()
    job.confirmed = true
    job.confirmedAt = new Date().toISOString()
    job.updatedAt = job.confirmedAt
    return
  }
  await api.post(`/ext/jobs/${id}/confirm`)
}

export async function getExtPrefill(id: string): Promise<PrefillPayload> {
  if (isDemo(id)) return demoPrefill(ensureDemoJob())
  const { data } = await api.get<PrefillPayload>(`/ext/jobs/${id}/prefill`)
  return data
}

export { DEMO_JOB_ID }
