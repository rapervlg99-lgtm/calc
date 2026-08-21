import { defineStore } from 'pinia'
import { fetchDicts, postCalc, exportFile } from '../utils/api'
import type { CalcRequest, CalcResponse, DictsResponse } from '../types/api'

export const useCalcStore = defineStore('calc', {
  state: () => ({
    dicts: null as DictsResponse | null,
    dictsError: null as string | null,
    loadingDicts: false,
    result: null as CalcResponse | null,
    loading: false,
    error: null as string | null
  }),
  actions: {
    async loadDicts() {
      this.loadingDicts = true
      this.dictsError = null
      try {
        this.dicts = await fetchDicts()
      } catch (e: any) {
        this.dictsError = e?.message || 'Не удалось загрузить справочники'
      } finally {
        this.loadingDicts = false
      }
    },
    async calculate(req: CalcRequest) {
      this.loading = true
      this.error = null
      try {
        this.result = await postCalc(req)
      } catch (e: any) {
        this.error = e?.response?.data?.error || e?.message || 'Ошибка расчёта'
        this.result = null
      } finally {
        this.loading = false
      }
    },
    async download(format: 'pdf' | 'xlsx' | 'docx') {
      if (!this.result?.id) throw new Error('нет calcId')
      const blob = await exportFile(format, this.result.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `ozm-report.${format}`
      a.click()
      URL.revokeObjectURL(url)
    }
  }
})
