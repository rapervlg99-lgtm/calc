<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useCalcStore } from '../stores/calc'
import { usePrefillStore } from '../stores/prefill'
import { mapPrefillPayload } from '../utils/prefillMapper'
import {
  applyGroupAttrs,
  findElement,
  moveToGroup,
  nextGroupTitle,
  nextUid,
  removeGroupKeepElements,
  uidOf
} from '../utils/elementGroups'
import { fmt, totalsOf, traceLinesFor } from '../utils/calcView'
import type { BetonInput, ElementInput, ElementResult, GroupInput } from '../types/api'
import TnCard from '../components/ui/TnCard.vue'
import TnButton from '../components/ui/TnButton.vue'
import TnInput from '../components/ui/TnInput.vue'
import TnNumberInput from '../components/ui/TnNumberInput.vue'
import TnSelect from '../components/ui/TnSelect.vue'
import TnCheckbox from '../components/ui/TnCheckbox.vue'
import TnTumbler from '../components/ui/TnTumbler.vue'
import TnTag from '../components/ui/TnTag.vue'
import TnIcon from '../components/ui/TnIcon.vue'
import ElementCard, { type FormElement } from '../components/calc/ElementCard.vue'
import ResultsTable from '../components/calc/ResultsTable.vue'
import MaterialsTable from '../components/calc/MaterialsTable.vue'

type FormGroup = {
  title: string
  quantity: number
  elements: FormElement[]
  /** общий предел ОС группы; '' — не задан */
  groupHt?: number | ''
  /** общий тип конструкции группы; '' — не задан */
  groupFr?: string
}

const store = useCalcStore()
const prefillStore = usePrefillStore()

const RED = 'var(--content-system-negative)'
const ORANGE = 'var(--content-system-warning)'
const GREEN = 'var(--content-system-positive)'

function emptyElement(over: Partial<FormElement> = {}): FormElement {
  return {
    _uid: nextUid(),
    title: '',
    shape: 'I-beam_sm',
    rollId: '79',
    dims: { h: 100, b: 55, s: 4.1, t: 5.7, R: 7 },
    frType: '1',
    htLevel: 60,
    sides: { left: true, top: true, right: true, bottom: true },
    lengthM: 3,
    quantity: 1,
    coat: '1',
    method: '1',
    primer: false,
    enamel: false,
    decor: true,
    ...over
  }
}
function emptyGroup(title = ''): FormGroup {
  return { title, quantity: 1, elements: [emptyElement()], groupHt: '', groupFr: '' }
}

const form = reactive({
  objectName: '',
  address: '',
  consent: false,
  frDurability: '1',
  groups: [emptyGroup()] as FormGroup[],
  betonOn: false,
  betonArea: null as number | null,
  betonR: '180'
})

const touched = ref(false)
const stale = ref(false)
const traceOpen = ref(false)
const exportMsg = ref('')
const prefillNote = ref('')
const dragUid = ref<number | null>(null)
const dragOverGroup = ref<number | null>(null)

// ---------- prefill из OCR ----------
function applyPendingPrefill() {
  const payload = prefillStore.consume()
  if (!payload) return
  const mapped = mapPrefillPayload(payload, store.dicts?.roll || [])
  if (!mapped.elements.length) {
    prefillNote.value = 'Предзаполнение пустое — элементы не изменены'
    return
  }
  form.groups = mapped.groups.map((g) => ({
    title: g.title,
    quantity: 1,
    groupHt: '',
    groupFr: '',
    elements: g.elements.map((m) => ({ ...m.element, profileMiss: m.profileMiss, _uid: nextUid() }))
  }))
  // Листовая сталь спецификации (фасонки, накладки, плиты) — это металл, а не
  // бетон: раньше её площадь включала тумблер ОЗБ и подставлялась как площадь
  // бетонных конструкций. Теперь ОЗБ задаёт только пользователь, а площадь
  // листа показывается справочно в заметке.
  const misses = mapped.elements.filter((m) => m.profileMiss).length
  const hits = mapped.elements.length - misses
  const groupNote = mapped.useGroups ? `, групп: ${mapped.groups.filter((g) => g.title).length}` : ''
  const sheetNote = mapped.sheetAreaM2 > 0
    ? ` Листовая сталь спецификации (${fmt(mapped.sheetAreaM2, 1)} м²) в расчёт не включена: калькулятор считает огнезащиту по элементам профильного проката.`
    : ''
  prefillNote.value = (misses
    ? `Предзаполнено ${mapped.elements.length} эл. из распознанной спецификации${groupNote}: ${hits} с маркой из справочника, ${misses} — выберите профиль вручную. Заполните объект, отметьте согласие и нажмите «Рассчитать».`
    : `Предзаполнено ${mapped.elements.length} эл. из распознанной спецификации${groupNote}, марки найдены в справочнике. Заполните объект, отметьте согласие и нажмите «Рассчитать».`) + sheetNote
}

onMounted(async () => {
  await store.loadDicts()
  applyPendingPrefill()
})

// ---------- справочники ----------
const dicts = computed(() => store.dicts)
const durabilityOptions = computed(() => (dicts.value?.selects.fr_durability || []).map((o) => ({ value: o.value, label: `${o.label} степень` })))
const betonROptions = [{ value: '180', label: 'R180' }, { value: '240', label: 'R240' }]

function coatLabel(v: string): string {
  return dicts.value?.selects.fr_coat.find((o) => o.value === v)?.label || v
}
function shapeLabel(id: string): string {
  for (const f of dicts.value?.profiles || []) for (const s of f.shapes) if (s.id === id) return s.label
  return id
}
function durabilityLabel(v: string): string {
  return dicts.value?.selects.fr_durability.find((o) => o.value === v)?.label || v
}

// ---------- группы и элементы ----------
const allElements = computed(() => form.groups.flatMap((g) => g.elements))
const groupOptions = computed(() => form.groups.map((g, i) => ({ value: String(i), label: g.title.trim() || `Группа ${i + 1}` })))

function markStale() {
  if (store.result) stale.value = true
}
function addGroup() {
  form.groups.push({ title: nextGroupTitle(form.groups), quantity: 1, elements: [emptyElement()], groupHt: '', groupFr: '' })
}
function removeGroup(gi: number) {
  if (form.groups.length <= 1) {
    form.groups[0].elements = []
    form.groups[0].title = ''
    return
  }
  removeGroupKeepElements(form.groups, gi)
}
function addElement(gi: number) {
  const g = form.groups[gi]
  const last = g.elements[g.elements.length - 1]
  g.elements.push(last ? emptyElement({ shape: last.shape, rollId: last.rollId, dims: { ...(last.dims || {}) }, frType: last.frType, htLevel: last.htLevel, coat: last.coat, method: last.method }) : emptyElement())
}
function copyElement(gi: number, ei: number) {
  const src = form.groups[gi]?.elements[ei]
  if (!src) return
  const clone: FormElement = structuredClone({ ...src })
  delete clone.id
  clone._uid = nextUid()
  clone.title = src.title ? `${src.title} (копия)` : ''
  form.groups[gi].elements.splice(ei + 1, 0, clone)
}
function removeElement(gi: number, ei: number) {
  form.groups[gi]?.elements.splice(ei, 1)
}
function moveElementTo(el: FormElement, gi: number) {
  moveToGroup(form.groups, [uidOf(el)], gi)
}
function groupIndexOf(el: FormElement): number {
  return findElement(form.groups, uidOf(el))?.gi ?? 0
}
function onGroupAttrs(gi: number) {
  const g = form.groups[gi]
  if (g) applyGroupAttrs(g)
}
function onDragStart(el: FormElement, e: DragEvent) {
  dragUid.value = uidOf(el)
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(dragUid.value))
  }
}
function onDropToGroup(gi: number) {
  dragOverGroup.value = null
  const uid = dragUid.value
  dragUid.value = null
  if (uid != null) moveToGroup(form.groups, [uid], gi)
}
function elementLabel(gi: number, ei: number): string {
  return `${gi + 1}.${ei + 1}`
}

// ---------- валидация ----------
type ElErrors = Record<number, { length?: string; quantity?: string }>
const validation = computed(() => {
  const errs = { objectName: '', address: '', consent: '', betonArea: '', elements: {} as ElErrors }
  let count = 0
  if (!form.objectName.trim()) { errs.objectName = 'Обязательное поле'; count++ }
  if (!form.address.trim()) { errs.address = 'Обязательное поле'; count++ }
  if (!form.consent) { errs.consent = 'Без согласия расчёт недоступен'; count++ }
  for (const g of form.groups) {
    for (const el of g.elements) {
      const e: { length?: string; quantity?: string } = {}
      if (!(Number(el.lengthM) > 0)) { e.length = 'Длина должна быть больше 0'; count++ }
      if (!(Number(el.quantity) > 0)) { e.quantity = 'Количество должно быть больше 0'; count++ }
      if (e.length || e.quantity) errs.elements[uidOf(el)] = e
    }
  }
  if (!allElements.value.length) count++
  if (form.betonOn && !(Number(form.betonArea) > 0)) { errs.betonArea = 'Площадь должна быть больше 0'; count++ }
  return { errs, count }
})
const shownErrors = computed(() => (touched.value ? validation.value.errs : { objectName: '', address: '', consent: '', betonArea: '', elements: {} as ElErrors }))

// ---------- запрос ----------
function mapEl(el: FormElement, i: number): ElementInput {
  const { _uid, profileMiss, construction, ...rest } = el
  void profileMiss
  void construction
  return {
    ...rest,
    id: `e${_uid ?? i}`,
    title: (el.title || '').trim() || `Элемент ${i + 1}`,
    method: el.coat === '1' ? el.method : '0'
  }
}
function buildGroups(): GroupInput[] {
  let i = 0
  return form.groups
    .filter((g) => g.elements.length)
    .map((g, gi) => ({
      id: `g${gi + 1}`,
      title: g.title.trim() || `Группа ${gi + 1}`,
      quantity: Number(g.quantity) || 1,
      elements: g.elements.map((el) => mapEl(el, i++))
    }))
}
function buildBeton(): BetonInput | null {
  if (!form.betonOn || !(Number(form.betonArea) > 0)) return null
  return { areaM2: Number(form.betonArea), htLevel: Number(form.betonR) }
}
async function runCalc() {
  touched.value = true
  if (validation.value.count) return
  exportMsg.value = ''
  const beton = buildBeton()
  await store.calculate({
    objectName: form.objectName.trim(),
    address: form.address.trim(),
    consent: true,
    frDurability: form.frDurability,
    groups: buildGroups(),
    ...(beton ? { beton } : {})
  })
  if (store.result) stale.value = false
}

watch(form, markStale, { deep: true })

async function download(fmtKind: 'pdf' | 'xlsx' | 'docx') {
  if (!store.result?.id) return
  try {
    await store.download(fmtKind)
    exportMsg.value = `Файл ozm-report.${fmtKind} сформирован и отправлен на скачивание`
  } catch (e: any) {
    exportMsg.value = `Не удалось выгрузить ${fmtKind}: ${e?.message || e}`
  }
}

// ---------- производные для отображения ----------
const result = computed(() => store.result)
const resultById = computed(() => {
  const m = new Map<string, ElementResult>()
  for (const r of result.value?.elements || []) m.set(r.id, r)
  return m
})
function resultFor(el: FormElement): ElementResult | undefined {
  return resultById.value.get(`e${el._uid}`)
}
const totals = computed(() => totalsOf(result.value?.elements || []))
const betonVolume = computed(() => result.value?.materials.filter((m) => m.id === 'OZB').reduce((a, m) => a + m.quantity, 0) || 0)
const messages = computed(() =>
  (result.value?.elements || [])
    .filter((r) => r.exclusion)
    .map((r) => ({
      id: r.id,
      title: r.title,
      text: r.exclusion || '',
      short: r.coat === '1.5' ? 'АКЗ — ручной ввод толщины' : 'Недостижимый предел при текущем δпр',
      color: r.coat === '1.5' ? ORANGE : RED
    }))
)
const totalLength = computed(() =>
  form.groups.reduce((a, g) => a + g.elements.reduce((b, el) => b + (Number(el.lengthM) || 0) * (Number(el.quantity) || 0), 0) * (Number(g.quantity) || 1), 0)
)
const traceLines = computed(() => result.value?.trace || [])
function traceFor(id: string): string[] {
  return traceLinesFor(result.value?.trace, id)
}

const calcLabel = computed(() => (stale.value ? 'Пересчитать' : result.value ? 'Рассчитать заново' : 'Рассчитать'))
const barHint = computed(() => {
  if (store.loading) return 'Отправка запроса на расчёт…'
  if (store.error) return store.error
  if (touched.value && validation.value.count) return `Не заполнено обязательных полей: ${validation.value.count}`
  if (exportMsg.value) return exportMsg.value
  if (stale.value) return 'Данные изменены после расчёта — пересчитайте'
  if (result.value) return `Расчёт выполнен · calcId ${result.value.id}`
  if (validation.value.count) return 'Заполните объект и отметьте согласие, чтобы рассчитать'
  return 'Готово к расчёту'
})
const barHintColor = computed(() =>
  store.error || (touched.value && validation.value.count) ? RED : stale.value ? ORANGE : exportMsg.value ? GREEN : 'var(--content-secondary-enabled)'
)
const barTitle = computed(() => {
  const base = `${form.groups.length} гр. · ${allElements.value.length} эл. · ${fmt(totalLength.value, 1)} м`
  return result.value ? `${base} · ${fmt(totals.value.area, 1)} м² огнезащиты` : base
})
</script>

<template>
  <div class="calc-page">
    <div class="calc-header">
      <div style="display: flex; flex-direction: column; gap: 4px">
        <h1 class="calc-title">Калькулятор огнезащиты металлоконструкций</h1>
        <div class="calc-subtitle">Подбор огнезащитных решений ТЕХНОНИКОЛЬ · ориентировочный расчёт по таблицам ТН и ГОСТ Р 53295</div>
      </div>
      <div style="display: flex; gap: 8px">
        <TnTag inline icon="fire">ОЗМ · ОЗБ · TAIKOR</TnTag>
      </div>
    </div>

    <div v-if="store.loadingDicts" class="calc-state">Загрузка справочников…</div>
    <div v-else-if="store.dictsError" class="calc-state">
      <div class="calc-banner calc-banner_error"><TnIcon name="info" :size="20" /><span>{{ store.dictsError }}</span></div>
      <TnButton secondary size="md" @click="store.loadDicts()">Повторить</TnButton>
    </div>

    <div v-else-if="dicts" class="calc-layout">
      <!-- Основная колонка -->
      <div class="calc-main">
        <div v-if="prefillNote" class="calc-banner"><TnIcon name="info" :size="20" /><span>{{ prefillNote }}</span></div>

        <TnCard>
          <div class="calc-col">
            <div class="calc-h2">Объект</div>
            <div class="calc-grid-object">
              <TnInput v-model="form.objectName" label="Наименование объекта" required :error="shownErrors.objectName" placeholder="БЦ «Северный», корпус 2" />
              <TnInput v-model="form.address" label="Адрес" required :error="shownErrors.address" placeholder="г. Рязань, ул. Промышленная, 17" />
              <TnSelect v-model="form.frDurability" label="Степень огнестойкости здания" required :options="durabilityOptions" />
            </div>
            <TnCheckbox v-model="form.consent" label="Согласие на обработку персональных данных" description="Без согласия расчёт не отправляется на сервер" :error="shownErrors.consent" />
          </div>
        </TnCard>

        <TnCard
          v-for="(g, gi) in form.groups"
          :key="gi"
          :class="{ 'calc-group-drop': dragOverGroup === gi }"
          @dragover.prevent="dragOverGroup = gi"
          @dragleave="dragOverGroup === gi && (dragOverGroup = null)"
          @drop.prevent="onDropToGroup(gi)"
        >
          <div class="calc-col">
            <div class="calc-group-head">
              <div style="flex: 1 1 auto; min-width: 160px">
                <TnInput v-model="g.title" label="Группа конструкций" :placeholder="`Группа ${gi + 1}`" />
              </div>
              <div style="flex: 0 0 132px">
                <TnNumberInput :model-value="g.quantity" label="Кол-во групп" required integer @update:model-value="(v) => (g.quantity = v ?? 1)" />
              </div>
              <div v-if="form.groups.length > 1 || g.elements.length > 1" style="flex: 0 0 120px">
                <TnSelect :model-value="g.groupHt === '' || g.groupHt === undefined ? '' : String(g.groupHt)" label="R для всех" placeholder="R…" :options="(dicts.selects.ht_level || [])" @update:model-value="(v) => { g.groupHt = v === '' ? '' : Number(v); onGroupAttrs(gi) }" />
              </div>
              <TnButton link icon="delete" @click="removeGroup(gi)">Удалить группу</TnButton>
            </div>

            <div v-if="!g.elements.length" class="calc-group-empty">Группа пуста — добавьте элемент или перетащите его сюда из другой группы.</div>

            <ElementCard
              v-for="(el, ei) in g.elements"
              :key="el._uid ?? ei"
              :el="el"
              :label="elementLabel(gi, ei)"
              :dicts="dicts"
              :result="resultFor(el)"
              :errors="shownErrors.elements[uidOf(el)]"
              :group-options="groupOptions"
              :group-index="groupIndexOf(el)"
              :draggable="form.groups.length > 1"
              @copy="copyElement(gi, ei)"
              @remove="removeElement(gi, ei)"
              @move="(to) => moveElementTo(el, to)"
              @dragstart="(e) => onDragStart(el, e)"
            />

            <div><TnButton secondary size="md" icon="add" @click="addElement(gi)">Добавить элемент</TnButton></div>
          </div>
        </TnCard>

        <div><TnButton outline size="md" icon="add" @click="addGroup">Добавить группу конструкций</TnButton></div>

        <TnCard>
          <div class="calc-col">
            <TnTumbler v-model="form.betonOn" block left-label label="Огнезащита бетонных конструкций (ОЗБ)" description="Плитная огнезащита по площади перекрытий и стен" />
            <div v-if="form.betonOn" class="calc-grid-4">
              <TnNumberInput v-model="form.betonArea" label="Площадь, м²" required :error="shownErrors.betonArea" />
              <TnSelect v-model="form.betonR" label="Предел огнестойкости R" required :options="betonROptions" />
              <div style="grid-column: span 2; display: flex; align-items: flex-end">
                <div class="calc-hint" style="padding-bottom: 10px">
                  {{ form.betonR === '240' ? `R240 → δ = ${dicts.config.ozbByR['240'] ?? 40} мм, плита ТЕХНО ОЗБ 110` : `R180 → δ = ${dicts.config.ozbByR['180'] ?? 50} мм, плита ТЕХНО ОЗБ 80` }}, коэффициент запаса {{ String(dicts.config.ozbQ).replace('.', ',') }}
                </div>
              </div>
            </div>
          </div>
        </TnCard>

        <div v-if="store.error" class="calc-banner calc-banner_error"><TnIcon name="info" :size="20" /><span>{{ store.error }}</span></div>

        <template v-if="result">
          <TnCard>
            <div class="calc-col">
              <div class="calc-row">
                <div class="calc-h1">Результаты по элементам</div>
                <TnTag v-if="result.id" inline>calcId {{ result.id.slice(0, 8) }}</TnTag>
                <div class="calc-grow" />
                <div class="calc-hint">Нажмите строку, чтобы раскрыть трейс расчёта</div>
              </div>
              <ResultsTable :rows="result.elements" :coat-label="coatLabel" :shape-label="shapeLabel" :trace-for="traceFor" />
            </div>
          </TnCard>

          <TnCard v-if="messages.length">
            <div class="calc-col-12">
              <div class="calc-h2">Сообщения расчёта</div>
              <div v-for="m in messages" :key="m.id" class="calc-msg">
                <div class="calc-msg-dot" :style="{ background: m.color }" />
                <div class="calc-msg-text"><span style="font-weight: 600">{{ m.title }}</span> — <span style="color: var(--content-secondary-enabled)">{{ m.text }}</span></div>
              </div>
            </div>
          </TnCard>

          <TnCard>
            <div class="calc-col">
              <div class="calc-row">
                <div class="calc-h1">Ведомость материалов</div>
                <div class="calc-grow" />
                <TnButton secondary icon="download" :disabled="!result.id" @click="download('xlsx')">Excel</TnButton>
                <TnButton secondary icon="download" :disabled="!result.id" @click="download('pdf')">PDF</TnButton>
                <TnButton secondary icon="download" :disabled="!result.id" @click="download('docx')">Word</TnButton>
              </div>
              <MaterialsTable :rows="result.materials" />
            </div>
          </TnCard>

          <TnCard v-if="traceLines.length">
            <div class="calc-col-12">
              <div class="calc-row">
                <div class="calc-h2">Трейс расчёта</div>
                <div class="calc-grow" />
                <TnButton link :icon-right="traceOpen ? 'up-s' : 'down-s'" @click="traceOpen = !traceOpen">{{ traceOpen ? 'Свернуть трейс' : 'Показать трейс' }}</TnButton>
              </div>
              <div v-if="traceOpen" class="calc-trace" style="gap: 4px">
                <div>calcId = {{ result.id }} · frDurability = {{ durabilityLabel(form.frDurability) }} · групп {{ result.inputs.groups.length }} · элементов {{ result.elements.length }}</div>
                <div>q ОЗМ = {{ dicts.config.ozmQ }} · q TAIKOR = {{ dicts.config.taikorQ }} · q ОЗБ = {{ dicts.config.ozbQ }}</div>
                <div v-for="(line, i) in traceLines" :key="i">{{ line }}</div>
              </div>
            </div>
          </TnCard>
        </template>
      </div>

      <!-- Боковая колонка -->
      <div class="calc-side">
        <TnCard>
          <div class="calc-col">
            <div class="calc-h2">Сводка</div>
            <div style="display: flex; flex-direction: column; gap: 10px">
              <div class="calc-summary-row"><div class="calc-summary-label">Объект</div><div class="calc-summary-value calc-ellipsis" style="max-width: 60%">{{ form.objectName.trim() || '—' }}</div></div>
              <div class="calc-summary-row"><div class="calc-summary-label">Степень огнестойкости</div><div class="calc-summary-value">{{ durabilityLabel(form.frDurability) }}</div></div>
              <div class="calc-summary-row"><div class="calc-summary-label">Групп / элементов</div><div class="calc-summary-value">{{ form.groups.length }} / {{ allElements.length }}</div></div>
              <div class="calc-summary-row"><div class="calc-summary-label">Общая длина</div><div class="calc-summary-value">{{ fmt(totalLength, 1) }} м</div></div>
              <div class="calc-summary-row"><div class="calc-summary-label">Бетон (ОЗБ)</div><div class="calc-summary-value">{{ form.betonOn ? `${fmt(Number(form.betonArea) || 0, 0)} м² · R${form.betonR}` : 'не считается' }}</div></div>
            </div>
            <div class="calc-divider" />
            <div style="display: flex; flex-direction: column; gap: 10px">
              <template v-if="result">
                <div class="calc-summary-row"><div class="calc-summary-label">Площадь огнезащиты</div><div class="calc-summary-value">{{ fmt(totals.area, 1) }} м²</div></div>
                <div class="calc-summary-row"><div class="calc-summary-label">Объём плитных материалов</div><div class="calc-summary-value">{{ fmt(totals.volumeM3 + betonVolume, 3) }} м³</div></div>
                <div class="calc-summary-row"><div class="calc-summary-label">Масса составов TAIKOR</div><div class="calc-summary-value">{{ fmt(totals.massKg, 1) }} кг</div></div>
                <div class="calc-summary-row"><div class="calc-summary-label">Сообщений расчёта</div><div class="calc-summary-value" :style="{ color: messages.length ? ORANGE : GREEN }">{{ messages.length }}</div></div>
              </template>
              <div v-else class="calc-summary-row"><div class="calc-summary-label">Результат</div><div class="calc-summary-value" style="color: var(--content-tertiary-enabled)">не рассчитан</div></div>
            </div>
            <div class="calc-hint" style="color: var(--content-tertiary-enabled)">{{ result && !stale ? 'Ведомость и выгрузки соответствуют текущим данным' : 'Итоги обновятся после расчёта' }}</div>
          </div>
        </TnCard>

        <TnCard v-if="messages.length">
          <div class="calc-col-12">
            <div class="calc-h2">Требует внимания</div>
            <div v-for="m in messages" :key="m.id" class="calc-msg">
              <div class="calc-msg-dot" :style="{ background: m.color }" />
              <div class="calc-msg-text"><span style="font-weight: 600">{{ m.title }}</span><br /><span style="color: var(--content-secondary-enabled)">{{ m.short }}</span></div>
            </div>
          </div>
        </TnCard>
      </div>
    </div>

    <!-- Нижняя панель действий -->
    <div v-if="dicts" class="calc-bar">
      <div class="calc-bar-text">
        <div class="calc-bar-title">{{ barTitle }}</div>
        <div class="calc-bar-hint" :style="{ color: barHintColor }">{{ barHint }}</div>
      </div>
      <div class="calc-grow" />
      <div v-if="result?.id" class="calc-bar-exports">
        <TnButton secondary size="md" icon="download" @click="download('xlsx')">Excel</TnButton>
        <TnButton secondary size="md" icon="download" @click="download('pdf')">PDF</TnButton>
        <TnButton secondary size="md" icon="download" @click="download('docx')">Word</TnButton>
        <div class="calc-bar-sep" />
      </div>
      <TnButton class="calc-btn-main" size="lg" icon="fire" :loading="store.loading" :disabled="touched && validation.count > 0" @click="runCalc">{{ calcLabel }}</TnButton>
    </div>
  </div>
</template>
