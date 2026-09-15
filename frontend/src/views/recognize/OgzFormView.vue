<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ProfileRowsTable from '../../components/ProfileRowsTable.vue'
import RowsTable from '../../components/RowsTable.vue'
import RowEditor from '../../components/RowEditor.vue'
import { DEMO_JOB_ID } from '../../fixtures/demoJob'
import { useJobStore } from '../../stores/job'
import { usePrefillStore } from '../../stores/prefill'
import { enrichPrefillWithGroups } from '../../utils/prefillMapper'
import type { OgzRow, OgzRowPatch } from '../../types/ogz'

const route = useRoute()
const router = useRouter()
const job = useJobStore()
const prefillStore = usePrefillStore()

const jobId = computed(() => String(route.params.id || ''))
const tab = ref<'profile' | 'sheet'>('profile')
const editorOpen = ref(false)
const editing = ref<OgzRow | null>(null)
const confirming = ref(false)
const prefilling = ref(false)
const msg = ref('')
const msgKind = ref<'ok' | 'err' | ''>('')
const importNotes = ref<string[]>([])
const profileTableRef = ref<InstanceType<typeof ProfileRowsTable> | null>(null)

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few
  return many
}

/** «3 строки — № 2, 5, 7» по номерам из колонки «№» соответствующей вкладки. */
function rowsPhrase(nums: number[]): string {
  return `${nums.length} ${plural(nums.length, 'строка', 'строки', 'строк')} — № ${nums.join(', ')}`
}
const missingRWord = computed(() =>
  job.missingFireLimitCount === 1 ? 'элемент' : 'элементов'
)

const canPrefill = computed(
  () => job.isConfirmed && job.prefillableCount > 0
)

const prefillTitle = computed(() => {
  if (!job.isConfirmed) return 'Сначала подтверди форму'
  if (job.prefillableCount === 0) {
    return 'Нет строк с назначенным пределом ОС (R)'
  }
  return ''
})

function notify(text: string, kind: 'ok' | 'err' = 'ok') {
  msg.value = text
  msgKind.value = kind
}

function reload(): void {
  void job.load(jobId.value)
}

async function fillDemo(): Promise<void> {
  await job.fillWithDemo()
  notify('Подставлены тестовые строки')
  if (jobId.value !== DEMO_JOB_ID) {
    await router.replace(`/recognize/jobs/${DEMO_JOB_ID}`)
  }
}

function openRowEditor(row: OgzRow): void {
  editing.value = row
  editorOpen.value = true
}

function closeEditor(): void {
  editorOpen.value = false
  editing.value = null
}

async function patchOne(rowId: number, patch: OgzRowPatch): Promise<void> {
  try {
    await job.patchRow(rowId, patch)
  } catch {
    notify('Не удалось сохранить строку', 'err')
  }
}

async function patchMany(rowIds: number[], patch: OgzRowPatch): Promise<void> {
  try {
    for (const id of rowIds) {
      await job.patchRow(id, patch)
    }
    notify(
      rowIds.length > 1
        ? `Обновлены ${rowIds.length} элементов группы`
        : 'Элемент обновлён'
    )
  } catch {
    notify('Не удалось применить атрибуты группы', 'err')
  }
}

async function saveRow(rowId: number, patch: OgzRowPatch): Promise<void> {
  try {
    await job.patchRow(rowId, patch)
    notify('Строка обновлена')
    closeEditor()
  } catch {
    notify('Не удалось сохранить строку', 'err')
  }
}

async function addRow(): Promise<void> {
  try {
    const created = await job.addRow()
    if (!created) {
      notify('Не удалось добавить элемент', 'err')
      return
    }
    notify('Элемент добавлен — заполни параметры')
    openRowEditor(created)
  } catch {
    notify('Не удалось добавить элемент', 'err')
  }
}

async function copyRow(row: OgzRow): Promise<void> {
  try {
    await job.copyRow(row.id)
    notify('Строка скопирована')
  } catch {
    notify('Не удалось скопировать строку', 'err')
  }
}

async function removeRow(row: OgzRow): Promise<void> {
  try {
    await job.removeRow(row.id)
    if (editing.value?.id === row.id) closeEditor()
    notify('Строка удалена')
  } catch {
    notify('Не удалось удалить строку', 'err')
  }
}

async function copyMany(rowIds: number[]): Promise<void> {
  try {
    for (const id of rowIds) {
      await job.copyRow(id)
    }
    notify(
      rowIds.length > 1
        ? `Скопированы ${rowIds.length} строк`
        : 'Строка скопирована'
    )
  } catch {
    notify('Не удалось скопировать строки', 'err')
  }
}

async function removeMany(rowIds: number[]): Promise<void> {
  try {
    for (const id of rowIds) {
      await job.removeRow(id)
    }
    if (editing.value && rowIds.includes(editing.value.id)) closeEditor()
    notify(
      rowIds.length > 1
        ? `Удалены ${rowIds.length} строк`
        : 'Строка удалена'
    )
  } catch {
    notify('Не удалось удалить строки', 'err')
  }
}

async function confirm(): Promise<void> {
  confirming.value = true
  try {
    await job.confirm()
    notify('Форма подтверждена')
  } catch {
    notify('Не удалось подтвердить форму', 'err')
  } finally {
    confirming.value = false
  }
}

async function prefill(): Promise<void> {
  if (!canPrefill.value) {
    notify('Назначь предел ОС (R) элементам перед отправкой в калькулятор', 'err')
    return
  }
  prefilling.value = true
  try {
    const payload = await job.fetchPrefill()
    if (!payload.items.length) {
      notify('Нет элементов с назначенным R для калькулятора', 'err')
      return
    }
    const tableGroups = profileTableRef.value?.getGroupsForPrefill?.() ?? []
    const enriched = enrichPrefillWithGroups(
      payload,
      job.profileRows,
      tableGroups
    )
    prefillStore.setPending(enriched)
    notify('Калькулятор открыт с предзаполненными данными')
    await router.push('/')
  } catch {
    notify('Не удалось сформировать предзаполнение', 'err')
  } finally {
    prefilling.value = false
  }
}

onMounted(async () => {
  await job.load(jobId.value)
  if (job.job?.id === DEMO_JOB_ID && jobId.value !== DEMO_JOB_ID) {
    await router.replace(`/recognize/jobs/${DEMO_JOB_ID}`)
  }
  // Заметки импорта из OCR — предупреждения («масса посчитана по размерам»,
  // «профиль не найден»), а не подтверждение действия: показываем их отдельным
  // жёлтым блоком над таблицей, а не зелёным уведомлением, и не даём затереть
  // следующим «Строка обновлена».
  importNotes.value = job.takeImportNotes()
})
</script>

<template>
  <div class="ozm-page recognize-page ogz">
    <div v-if="job.loading && !job.job" class="ogz__state">
      <p>Загружаем расчёт…</p>
    </div>

    <div v-else-if="job.error && !job.job" class="ogz__state">
      <p class="error">{{ job.error }}</p>
      <button type="button" class="btn-primary" @click="reload">Повторить</button>
    </div>

    <template v-else-if="job.job">
      <div class="ogz__top">
        <div class="ogz__heading">
          <div class="ozm-top" style="margin-bottom: 0">
            <h1 class="ozm-title">Форма расчёта ОГЗ</h1>
            <router-link class="btn-ghost" to="/recognize">← Загрузка</router-link>
          </div>
          <p class="ogz__subtitle">
            Проверь строки, заполни ручные атрибуты и подтверди форму перед
            отправкой в калькулятор огнезащиты.
          </p>
        </div>
        <div class="ogz__actions">
          <button
            type="button"
            class="btn-ghost"
            :disabled="job.isConfirmed || confirming"
            @click="confirm"
          >
            {{ job.isConfirmed ? 'Форма подтверждена' : 'Подтвердить форму' }}
          </button>
          <button
            type="button"
            class="btn-primary"
            :disabled="!canPrefill || prefilling"
            :title="prefillTitle"
            @click="prefill"
          >
            Предзаполнить калькулятор
          </button>
        </div>
      </div>

      <!-- Один блок вместо двух: «где» (вкладка и номера строк — живой список,
           пустеет по мере правок) и «почему» (заметки импорта из OCR, статичные,
           можно скрыть). Блок «без предела ОС» остаётся отдельным: это другое
           действие и другой момент — перед отправкой в калькулятор. -->
      <div v-if="job.needsAttentionCount > 0 || importNotes.length" class="ogz__banner ogz__banner_check" role="status">
        <div class="ogz__banner-title">Что проверить после распознавания</div>
        <template v-if="job.needsAttentionCount > 0">
          <div class="ogz__banner-sub">Требуют проверки или ввода массы — проверь перед подтверждением:</div>
          <ul class="ogz__banner-list">
            <li v-if="job.attentionRows.profile.length">
              <button type="button" class="ogz__banner-link" @click="tab = 'profile'">Профильный погонаж</button>:
              {{ rowsPhrase(job.attentionRows.profile) }}
            </li>
            <li v-if="job.attentionRows.sheet.length">
              <button type="button" class="ogz__banner-link" @click="tab = 'sheet'">Листовая сталь</button>:
              {{ rowsPhrase(job.attentionRows.sheet) }}
            </li>
          </ul>
        </template>
        <template v-if="importNotes.length">
          <div class="ogz__banner-sub">Почему:</div>
          <ul class="ogz__banner-list ogz__banner-list_notes">
            <li v-for="(n, i) in importNotes" :key="i">{{ n }}</li>
          </ul>
          <button type="button" class="btn-ghost btn-sm ogz__banner-close" aria-label="Скрыть заметки импорта" @click="importNotes = []">Скрыть</button>
        </template>
      </div>

      <div v-if="job.missingFireLimitCount > 0" class="ogz__banner ogz__banner_info">
        <span>
          {{ job.missingFireLimitCount }}
          {{ missingRWord }} без предела ОС (R) — в калькулятор не уйдут, пока не
          назначишь R (удобно через «Группа элементов»).
        </span>
      </div>

      <p v-if="msg" class="ogz__msg" :class="{ 'ogz__msg_err': msgKind === 'err' }">{{ msg }}</p>

      <div class="ogz-card">
        <div class="ogz__tabs" role="tablist">
          <button
            type="button"
            class="ogz__tab"
            :class="{ ogz__tab_active: tab === 'profile' }"
            role="tab"
            :aria-selected="tab === 'profile'"
            @click="tab = 'profile'"
          >
            Профильный погонаж ({{ job.profileRows.length }})
          </button>
          <button
            type="button"
            class="ogz__tab"
            :class="{ ogz__tab_active: tab === 'sheet' }"
            role="tab"
            :aria-selected="tab === 'sheet'"
            @click="tab = 'sheet'"
          >
            Листовая сталь ({{ job.sheetRows.length }})
          </button>
        </div>

        <div
          v-if="job.profileRows.length === 0 && job.sheetRows.length === 0"
          class="ogz__empty-fill"
        >
          <p>В задании нет строк — добавь элемент вручную или подставь тестовые данные.</p>
          <div class="ogz__empty-actions">
            <button type="button" class="btn-primary" @click="addRow">+ Добавить элемент</button>
            <button type="button" class="btn-ghost" @click="fillDemo">Заполнить демо-данными</button>
          </div>
        </div>

        <template v-else>
          <ProfileRowsTable
            v-show="tab === 'profile'"
            ref="profileTableRef"
            :rows="job.profileRows"
            empty-text="В этом задании нет профильных строк."
            @edit="openRowEditor"
            @add="addRow"
            @copy="copyRow"
            @remove="removeRow"
            @copy-many="copyMany"
            @remove-many="removeMany"
            @patch="patchOne"
            @patch-many="patchMany"
          />
          <RowsTable
            v-show="tab === 'sheet'"
            kind="sheet"
            :rows="job.sheetRows"
            empty-text="В этом задании нет листовой стали."
            @edit="openRowEditor"
            @patch="patchOne"
          />
        </template>
      </div>
    </template>

    <RowEditor
      :open="editorOpen"
      :row="editing"
      @close="closeEditor"
      @save="saveRow"
    />
  </div>
</template>

<style scoped>
.ogz {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ogz__state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 240px;
  color: var(--content-secondary-enabled);
}

.ogz__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.ogz__heading {
  flex: 1;
  min-width: 0;
}

.ogz__subtitle {
  margin: 8px 0 0;
  color: var(--content-secondary-enabled);
  line-height: 22px;
}

.ogz__actions {
  flex: 0 0 auto;
  display: flex;
  gap: 8px;
}

.ogz__banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-radius: 12px;
  color: var(--content-system-warning);
  background: var(--orange-10);
}

.ogz__banner_info {
  color: var(--content-secondary-enabled);
  background: var(--background-secondary-enabled);
}

.ogz__banner_check {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: start;
  color: var(--content-primary-a-enabled);
}

.ogz__banner_check > * {
  grid-column: 1;
}

.ogz__banner_check .ogz__banner-close {
  grid-column: 2;
  grid-row: 1;
}

.ogz__banner-sub {
  margin-top: 6px;
  font-weight: 600;
  font-size: 14px;
}

.ogz__banner-list_notes {
  color: var(--content-secondary-enabled);
  font-size: 13px;
  line-height: 18px;
}

.ogz__banner-link {
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  font-weight: 600;
  color: var(--content-primary-a-enabled);
  text-decoration: underline;
  cursor: pointer;
}

.ogz__banner-link:hover {
  color: var(--content-accent-enabled);
}

.ogz__banner-title {
  font-weight: 600;
  color: var(--content-system-warning);
}

.ogz__banner-list {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 14px;
  line-height: 20px;
}

.ogz__msg {
  margin: 0;
  color: var(--content-system-positive);
  font-size: 14px;
}

.ogz__msg_err {
  color: var(--content-system-negative);
}

.ogz-card {
  padding: 8px 0 16px;
  border: 1px solid var(--line-soft);
  border-radius: 12px;
  background: #fff;
}

.ogz__tabs {
  display: flex;
  gap: 4px;
  padding: 0 16px 12px;
  border-bottom: 1px solid var(--line-soft);
  margin-bottom: 8px;
}

.ogz__tab {
  border: none;
  background: transparent;
  padding: 10px 14px;
  border-radius: 8px;
  font: inherit;
  font-size: 14px;
  color: var(--content-secondary-enabled);
  cursor: pointer;
}

.ogz__tab_active {
  background: var(--soft);
  color: var(--text);
  font-weight: 600;
}

.ogz__empty-fill {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px 16px;
  color: var(--content-secondary-enabled);
  text-align: center;
}

.ogz__empty-fill p {
  margin: 0;
}

.ogz__empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

@media (width <= 800px) {
  .ogz__top {
    flex-direction: column;
    align-items: stretch;
  }

  .ogz__actions {
    flex-direction: column;
  }
}
</style>
