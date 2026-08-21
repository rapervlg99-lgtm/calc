import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { PrefillPayload } from '../types/ogz'

const KEY = 'ozm-pending-prefill'

/** Holds PrefillPayload between /recognize → CalculatorView. */
export const usePrefillStore = defineStore('prefill', () => {
  const pending = ref<PrefillPayload | null>(null)

  function setPending(payload: PrefillPayload) {
    pending.value = payload
    try {
      sessionStorage.setItem(KEY, JSON.stringify(payload))
    } catch {
      /* ignore quota */
    }
  }

  function consume(): PrefillPayload | null {
    if (pending.value) {
      const p = pending.value
      pending.value = null
      try { sessionStorage.removeItem(KEY) } catch { /* */ }
      return p
    }
    try {
      const raw = sessionStorage.getItem(KEY)
      if (!raw) return null
      sessionStorage.removeItem(KEY)
      return JSON.parse(raw) as PrefillPayload
    } catch {
      return null
    }
  }

  return { pending, setPending, consume }
})
