import axios from 'axios'
import type { CalcRequest, CalcResponse, DictsResponse } from '../types/api'

export const api = axios.create({ baseURL: '/api/v1', timeout: 60000 })

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
