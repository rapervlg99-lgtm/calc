import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  confirmExtJob,
  copyExtRow,
  createExtRow,
  deleteExtRow,
  DEMO_JOB_ID,
  getExtJob,
  getExtPrefill,
  isLocalJob,
  patchExtRow,
  resetDemoJob
} from '../utils/extApi'
import type { Job, OgzRow, OgzRowPatch, PrefillPayload } from '../types/ogz'

function isEmptyJob(job: Job): boolean {
  return job.profileRows.length === 0 && job.sheetRows.length === 0
}

export const useJobStore = defineStore('job', () => {
  const job = ref<Job | null>(null)
  const loading = ref(false)
  const error = ref('')
  const lastPrefill = ref<PrefillPayload | null>(null)
  /** Замечания импорта из локального OCR — показываются один раз в форме. */
  const importNotes = ref<string[]>([])

  const profileRows = computed(() => job.value?.profileRows ?? [])
  const sheetRows = computed(() => job.value?.sheetRows ?? [])
  const isConfirmed = computed(() => job.value?.confirmed ?? false)

  const needsAttention = (r: OgzRow) =>
    r.status === 'Требует проверки' || r.status === 'Нужен ввод массы' || r.status === 'Нет данных'

  const needsAttentionCount = computed(
    () => [...profileRows.value, ...sheetRows.value].filter(needsAttention).length
  )

  /**
   * Номера строк (как в колонке «№» таблиц — порядковый номер в перечне
   * профильного погонажа и листовой стали), которые требуют проверки или ввода
   * массы. Отдельно по вкладкам: предупреждение называет вкладку и номера.
   */
  const attentionRows = computed(() => ({
    profile: profileRows.value.map((r, i) => (needsAttention(r) ? i + 1 : 0)).filter(Boolean),
    sheet: sheetRows.value.map((r, i) => (needsAttention(r) ? i + 1 : 0)).filter(Boolean)
  }))

  const missingFireLimitCount = computed(() =>
    profileRows.value.filter(
      (r) =>
        (r.status === 'Посчитано' || r.status === 'Требует проверки') &&
        !r.fireLimit.trim()
    ).length
  )

  const prefillableCount = computed(() =>
    profileRows.value.filter(
      (r) =>
        (r.status === 'Посчитано' || r.status === 'Требует проверки') &&
        r.lengthM > 0 &&
        r.fireLimit.trim() !== ''
    ).length
  )

  async function load(id: string) {
    loading.value = true
    error.value = ''
    try {
      job.value = await getExtJob(id)
      // Пустое серверное задание подменяем демо; задание из локального OCR
      // оставляем как есть — его пустота значима для пользователя.
      if (job.value && isEmptyJob(job.value) && !isLocalJob(id)) {
        await fillWithDemo()
      }
    } catch (e: any) {
      error.value = e?.message || 'Не удалось загрузить задание'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fillWithDemo() {
    resetDemoJob()
    job.value = await getExtJob(DEMO_JOB_ID)
    error.value = ''
  }

  function replaceRow(row: OgzRow) {
    if (!job.value) return
    const list = row.isSheet ? job.value.sheetRows : job.value.profileRows
    const idx = list.findIndex((r) => r.id === row.id)
    if (idx !== -1) list.splice(idx, 1, row)
  }

  function insertRowAfter(sourceId: number, row: OgzRow) {
    if (!job.value) return
    const list = row.isSheet ? job.value.sheetRows : job.value.profileRows
    // Avoid double-insert when demo API already mutated the shared job and we reloaded.
    if (list.some((r) => r.id === row.id)) return
    const idx = list.findIndex((r) => r.id === sourceId)
    if (idx === -1) list.push(row)
    else list.splice(idx + 1, 0, row)
  }

  function dropRow(rowId: number) {
    if (!job.value) return
    const drop = (rows: OgzRow[]) => {
      const i = rows.findIndex((r) => r.id === rowId)
      if (i !== -1) rows.splice(i, 1)
    }
    drop(job.value.profileRows)
    drop(job.value.sheetRows)
  }

  async function patch(rowId: number, body: OgzRowPatch) {
    if (!job.value) return
    const updated = await patchExtRow(job.value.id, rowId, body)
    replaceRow(updated)
    job.value.updatedAt = new Date().toISOString()
  }

  /** Alias used by ported OGZ form. */
  async function patchRow(rowId: number, body: OgzRowPatch) {
    await patch(rowId, body)
  }

  async function addRow(): Promise<OgzRow | null> {
    if (!job.value) return null
    const created = await createExtRow(job.value.id)
    if (!job.value.profileRows.some((r) => r.id === created.id)) {
      job.value.profileRows.push(created)
    }
    job.value.updatedAt = new Date().toISOString()
    return created
  }

  async function copyRow(rowId: number) {
    if (!job.value) return
    const created = await copyExtRow(job.value.id, rowId)
    insertRowAfter(rowId, created)
    job.value.updatedAt = new Date().toISOString()
  }

  async function removeRow(rowId: number) {
    if (!job.value) return
    await deleteExtRow(job.value.id, rowId)
    dropRow(rowId)
    job.value.updatedAt = new Date().toISOString()
  }

  async function confirm() {
    if (!job.value) return
    await confirmExtJob(job.value.id)
    job.value.confirmed = true
    job.value.confirmedAt = new Date().toISOString()
  }

  async function fetchPrefill(): Promise<PrefillPayload> {
    if (!job.value) throw new Error('no job')
    const payload = await getExtPrefill(job.value.id)
    lastPrefill.value = payload
    return payload
  }

  function openDemo() {
    resetDemoJob()
  }

  function setImportNotes(notes: string[]) {
    importNotes.value = [...notes]
  }

  function takeImportNotes(): string[] {
    const n = importNotes.value
    importNotes.value = []
    return n
  }

  return {
    job,
    loading,
    error,
    lastPrefill,
    importNotes,
    profileRows,
    sheetRows,
    isConfirmed,
    needsAttentionCount,
    attentionRows,
    missingFireLimitCount,
    prefillableCount,
    load,
    fillWithDemo,
    patch,
    patchRow,
    addRow,
    copyRow,
    removeRow,
    confirm,
    fetchPrefill,
    openDemo,
    setImportNotes,
    takeImportNotes
  }
})
