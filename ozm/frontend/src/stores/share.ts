import { defineStore } from 'pinia'
import { createShare, loadShare, updateShare, type SharePayload } from '../utils/api'

/**
 * Ссылка обмена расчётом: создаётся при входе в калькулятор, дальше состояние
 * дописывается в неё по мере правок. Токен живёт в адресе страницы и в этом
 * сторе; все запросы — через /api/v1/share.
 */
export const useShareStore = defineStore('share', {
  state: () => ({
    token: null as string | null,
    status: 'idle' as 'idle' | 'loading' | 'ready' | 'error',
    saving: false,
    error: null as string | null,
    savedAt: 0 as number
  }),
  getters: {
    link: (s) => (s.token ? s.token : '')
  },
  actions: {
    /** Открыть расчёт по токену; null — ссылка не найдена. */
    async open(token: string): Promise<SharePayload | null> {
      this.status = 'loading'
      this.error = null
      try {
        const data = await loadShare(token)
        this.token = data.token || token
        this.status = 'ready'
        return (data.payload as SharePayload) || null
      } catch (e: any) {
        this.status = 'error'
        this.error = e?.response?.data?.error || e?.message || 'Не удалось открыть расчёт по ссылке'
        return null
      }
    },
    /** Создать новую ссылку для текущего состояния. */
    async create(payload: SharePayload): Promise<string | null> {
      this.error = null
      try {
        const data = await createShare(payload)
        this.token = data.token
        this.status = 'ready'
        this.savedAt = Date.now()
        return data.token
      } catch (e: any) {
        this.error = e?.response?.data?.error || e?.message || 'Не удалось создать ссылку'
        this.status = 'error'
        return null
      }
    },
    /** Дописать правки в ссылку (молча: это фоновая синхронизация). */
    async save(payload: SharePayload): Promise<void> {
      if (!this.token || this.saving) return
      this.saving = true
      try {
        await updateShare(this.token, payload)
        this.savedAt = Date.now()
        this.error = null
      } catch (e: any) {
        this.error = e?.response?.data?.error || e?.message || 'Правки не сохранились в ссылку'
      } finally {
        this.saving = false
      }
    }
  }
})