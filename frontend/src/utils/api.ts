import axios from 'axios'
import type { CalcRequest, CalcResponse, DictsResponse } from '../types/api'

/** Префикс приложения с завершающим слешем: «/» или «/ozm/» (vite base). */
export const APP_BASE = (import.meta.env.BASE_URL || '/').replace(/\/?$/, '/')

export const api = axios.create({ baseURL: `${APP_BASE}api/v1`, timeout: 60000 })

/**
 * Bearer на каждый запрос /api. Бэкенд в AUTH_DEV_MODE принимает любой токен,
 * а на сервере nginx пропускает в /api/ только токен, зашитый при сборке
 * (VITE_AUTH_DEV_TOKEN = API_TOKEN, см. dev/deploy). Интерцептор живёт здесь,
 * а не в extApi.ts, чтобы calc-запросы не зависели от порядка импорта модулей.
 */
const AUTH_TOKEN = import.meta.env.VITE_AUTH_DEV_TOKEN || 'dev-token'
api.interceptors.request.use((cfg) => {
  if (!cfg.headers.Authorization) {
    cfg.headers.Authorization = `Bearer ${AUTH_TOKEN}`
  }
  return cfg
})

export async function fetchDicts(): Promise<DictsResponse> {
  const { data } = await api.get<DictsResponse>('/dicts')
  return data
}

export async function postCalc(req: CalcRequest): Promise<CalcResponse> {
  const { data } = await api.post<CalcResponse>('/calc', req)
  return data
}

export async function exportFile(format: 'pdf' | 'xlsx' | 'docx', calcId: string): Promise<Blob> {
  const { data } = await api.post(`/export/${format}`, { calcId }, { responseType: 'blob' })
  return data
}
