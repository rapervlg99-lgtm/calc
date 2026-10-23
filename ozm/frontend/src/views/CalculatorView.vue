<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useCalcStore } from '../stores/calc'
import { usePrefillStore } from '../stores/prefill'
import { useShareStore } from '../stores/share'
import { shareTokenFromUrl, urlWithShareToken, urlWithoutShareToken } from '../utils/share'
import type { SharePayload } from '../utils/api'
import { mapPrefillPayload } from '../utils/prefillMapper'
import {
  applyGroupAttrs,
  findElement,
  moveToBlock,
  nextGroupTitle,
  nextUid,
  removeGroupKeepElements,
  requestBlockPlan,
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
const shareStore = useShareStore()
const router = useRouter()

/** Вход в распознавание таблиц ИД. Вкладок разделов больше нет: решение
 *  «вручную или распознаванием» пользователь принимает в области первой
 *  конструкции (см. .calc-ocr-cta), а страница распознавания несёт свою ссылку
 *  «← К калькулятору». */
function goRecognize() {
  router.push('/recognize')
}

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
  // Группа создаётся пустой: конструкция в неё попадает переносом (селектором
  // «Без группы» или перетаскиванием), а не рождается вместе с группой.
  return { title, quantity: 1, elements: [], groupHt: '', groupFr: '' }
}

const form = reactive({
  objectName: '',
  address: '',
  consent: false,
  frDurability: '1',
  /** Конструкции без группы — состояние по умолчанию: одна конструкция, ни одной группы. */
  ungrouped: [emptyElement()] as FormElement[],
  groups: [] as FormGroup[],
  betonOn: false,
  betonArea: null as number | null,
  betonR: '180'
})

const touched = ref(false)
const stale = ref(false)
const traceOpen = ref(false)
const exportMsg = ref('')
const prefillNote = ref('')
const shareNote = ref('')
const dragUid = ref<number | null>(null)
const dragOverBlock = ref<number | null>(null)

// ---------- prefill из OCR ----------
function applyPendingPrefill() {
  const payload = prefillStore.consume()
  if (!payload) return
  const mapped = mapPrefillPayload(payload, store.dicts?.roll || [])
  if (!mapped.elements.length) {
    prefillNote.value = 'Предзаполнение пустое — элементы не изменены'
    return
  }
  form.ungrouped = []
  form.groups = []
  const toElement = (m: (typeof mapped.elements)[number]): FormElement => ({
    ...m.element,
    profileMiss: m.profileMiss,
    _uid: nextUid()
  })
  // Группы без названия (в том числе единственная, когда группировка выключена) —
  // это конструкции без группы: они идут в общий список, а не в панель группы.
  for (const g of mapped.groups) {
    if (g.title.trim()) {
      form.groups.push({ title: g.title, quantity: 1, groupHt: '', groupFr: '', elements: g.elements.map(toElement) })
    } else {
      form.ungrouped.push(...g.elements.map(toElement))
    }
  }
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

// ---------- ссылка обмена расчётом ----------
// Состояние формы целиком уходит в ссылку (?n<timestamp>): при входе ссылка
// создаётся сразу, дальше правки дописываются в неё с задержкой. Открывший
// ссылку видит тот же расчёт и может его пересчитать или выгрузить.
let saveTimer: number | undefined
let lastJson = ''

function snapshot(): SharePayload {
  return { v: 1, form: JSON.parse(JSON.stringify(form)) }
}

/** Приводит элемент из ссылки к форме: недостающее берём из пустого элемента. */
function normalizeElement(raw: unknown): FormElement {
  const src = (raw || {}) as Partial<FormElement>
  const base = emptyElement()
  return {
    ...base,
    ...src,
    dims: { ...base.dims, ...(src.dims || {}) },
    sides: { ...base.sides, ...(src.sides || {}) },
    _uid: nextUid()
  }
}

/** Восстанавливает форму из ссылки; false — данные не похожи на расчёт. */
function hydrate(payload: SharePayload | null): boolean {
  const src = ((payload as any)?.form ?? payload) as Record<string, any> | null
  if (!src || typeof src !== 'object') return false
  form.objectName = String(src.objectName || '')
  form.address = String(src.address || '')
  // согласие на обработку данных каждый пользователь даёт сам
  form.consent = false
  form.frDurability = String(src.frDurability || '1')
  form.betonOn = Boolean(src.betonOn)
  form.betonArea = src.betonArea == null ? null : Number(src.betonArea)
  form.betonR = String(src.betonR || '180')
  form.ungrouped = Array.isArray(src.ungrouped) && src.ungrouped.length ? src.ungrouped.map(normalizeElement) : [emptyElement()]
  form.groups = Array.isArray(src.groups)
    ? src.groups.map((g: any) => ({
        title: String(g?.title || ''),
        quantity: Number(g?.quantity) || 1,
        groupHt: g?.groupHt ?? '',
        groupFr: g?.groupFr ?? '',
        elements: Array.isArray(g?.elements) ? g.elements.map(normalizeElement) : []
      }))
    : []
  return true
}

/** Записывает токен в адресную строку, не создавая записи в истории. */
function putTokenToUrl(token: string) {
  const next = urlWithShareToken(window.location.href, token)
  if (next !== window.location.href) window.history.replaceState(window.history.state, '', next)
}

async function initShare() {
  const token = shareTokenFromUrl(window.location.href)
  if (token) {
    const payload = await shareStore.open(token)
    if (payload && hydrate(payload)) {
      lastJson = JSON.stringify(snapshot())
      shareNote.value = ''
      return
    }
    // ссылка битая или устаревшая — начинаем с чистой и создаём новую
    window.history.replaceState(window.history.state, '', urlWithoutShareToken(window.location.href))
  }
  const created = await shareStore.create(snapshot())
  if (created) {
    lastJson = JSON.stringify(snapshot())
    putTokenToUrl(created)
  } else {
    shareNote.value = shareStore.error || 'Ссылка для обмена недоступна'
  }
}

/** Отложенная запись правок: не дёргаем сервер на каждое нажатие клавиши. */
function scheduleShareSave() {
  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(async () => {
    const payload = snapshot()
    const json = JSON.stringify(payload)
    if (json === lastJson) return
    lastJson = json
    await shareStore.save(payload)
    if (shareStore.error) shareNote.value = shareStore.error
  }, 800)
}

async function copyShareLink() {
  const href = shareStore.token ? urlWithShareToken(window.location.href, shareStore.token) : window.location.href
  try {
    await navigator.clipboard.writeText(href)
    shareNote.value = 'Ссылка на расчёт скопирована'
  } catch {
    shareNote.value = href
  }
}

onMounted(async () => {
  await store.loadDicts()
  applyPendingPrefill()
  await initShare()
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

// ---------- конструкции и группы ----------
// Блок — то, что рисуется карточкой на экране: конструкции без группы (ordinal 0)
// и группы пользователя (ordinal 1…N, он же префикс нумерации элементов «1.1»).
type Block = { ordinal: number; group?: FormGroup; elements: FormElement[] }

const allElements = computed(() => [...form.ungrouped, ...form.groups.flatMap((g) => g.elements)])
const groupOptions = computed(() => [
  { value: '0', label: 'Без группы' },
  ...form.groups.map((g, i) => ({ value: String(i + 1), label: g.title.trim() || `Группа ${i + 1}` }))
])
const blocks = computed<Block[]>(() => {
  const list: Block[] = []
  // Список «без группы» показываем, пока в нём есть конструкции или пока групп
  // нет вовсе: иначе после переноса всего в группы некуда было бы добавить новую.
  if (form.ungrouped.length || !form.groups.length) list.push({ ordinal: 0, elements: form.ungrouped })
  form.groups.forEach((g, i) => list.push({ ordinal: i + 1, group: g, elements: g.elements }))
  return list
})

function elementsOf(ordinal: number): FormElement[] | undefined {
  return ordinal === 0 ? form.ungrouped : form.groups[ordinal - 1]?.elements
}

/** Блок с первой конструкцией: там же стоит выбор «вручную или распознавание»,
 *  поэтому перенос конструкции в группу этот выбор не убирает. */
const firstFilledOrdinal = computed(() => blocks.value.find((b) => b.elements.length)?.ordinal ?? -1)

function markStale() {
  if (store.result) stale.value = true
}
function addGroup() {
  // Пустая группа: конструкция в неё попадает переносом, а не создаётся вместе с ней.
  form.groups.push(emptyGroup(nextGroupTitle(form.groups)))
}
function removeGroup(ordinal: number) {
  const gi = ordinal - 1
  if (gi < 0 || !form.groups[gi]) return
  // Элементы удалённой группы возвращаются в список «без группы».
  removeGroupKeepElements(form.groups, gi, form.ungrouped)
}
function addElement(ordinal: number) {
  const list = elementsOf(ordinal)
  if (!list) return
  const last = list[list.length - 1]
  list.push(
    last
      ? emptyElement({ shape: last.shape, rollId: last.rollId, dims: { ...(last.dims || {}) }, frType: last.frType, htLevel: last.htLevel, coat: last.coat, method: last.method })
      : emptyElement()
  )
}
function copyElement(ordinal: number, ei: number) {
  const list = elementsOf(ordinal)
  const src = list?.[ei]
  if (!list || !src) return
  const clone: FormElement = structuredClone({ ...src })
  delete clone.id
  clone._uid = nextUid()
  clone.title = src.title ? `${src.title} (копия)` : ''
  list.splice(ei + 1, 0, clone)
}
function removeElement(ordinal: number, ei: number) {
  elementsOf(ordinal)?.splice(ei, 1)
}
/** Перенос по ordinal: 0 — «без группы», 1…N — номер группы. */
function moveByUid(uid: number, ordinal: number) {
  moveToBlock(form.ungrouped, form.groups, [uid], ordinal)
}
function moveElementTo(el: FormElement, ordinal: number) {
  moveByUid(uidOf(el), ordinal)
}
/** Номер блока для селектора группы: 0 — конструкция вне группы. */
function blockOrdinalOf(el: FormElement): number {
  const found = findElement(form.groups, uidOf(el))
  return found ? found.gi + 1 : 0
}
function onGroupAttrs(ordinal: number) {
  const g = form.groups[ordinal - 1]
  if (g) applyGroupAttrs(g)
}
function setGroupQuantity(b: Block, v: number | null) {
  if (b.group) b.group.quantity = v ?? 1
}
function setGroupHt(b: Block, v: string) {
  if (!b.group) return
  b.group.groupHt = v === '' ? '' : Number(v)
  applyGroupAttrs(b.group)
}
function onDragStart(el: FormElement, e: DragEvent) {
  dragUid.value = uidOf(el)
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(dragUid.value))
  }
}
function onDropToBlock(ordinal: number) {
  dragOverBlock.value = null
  const uid = dragUid.value
  dragUid.value = null
  if (uid != null) moveByUid(uid, ordinal)
}
/** Нумерация элементов: «1», «2» вне группы и «1.1», «1.2» внутри группы. */
function elementLabel(ordinal: number, ei: number): string {
  return ordinal ? `${ordinal}.${ei + 1}` : `${ei + 1}`
}

// ---------- валидация ----------
type ElErrors = Record<number, { length?: string; quantity?: string }>
const validation = computed(() => {
  const errs = { objectName: '', address: '', consent: '', betonArea: '', elements: {} as ElErrors }
  let count = 0
  if (!form.objectName.trim()) { errs.objectName = 'Обязательное поле'; count++ }
  if (!form.address.trim()) { errs.address = 'Обязательное поле'; count++ }
  if (!form.consent) { errs.consent = 'Без согласия расчёт недоступен'; count++ }
  for (const el of allElements.value) {
    const e: { length?: string; quantity?: string } = {}
    if (!(Number(el.lengthM) > 0)) { e.length = 'Длина должна быть больше 0'; count++ }
    if (!(Number(el.quantity) > 0)) { e.quantity = 'Количество должно быть больше 0'; count++ }
    if (e.length || e.quantity) errs.elements[uidOf(el)] = e
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
  // Конструкции без группы уходят первой группой с пустым названием: контракт
  // требует хотя бы одну группу, а количество 1 ничего не домножает.
  return requestBlockPlan(form.ungrouped, form.groups).map((b, bi) => ({
    id: `g${bi + 1}`,
    title: b.title,
    quantity: b.quantity,
    elements: b.elements.map((el) => mapEl(el, i++))
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

watch(
  form,
  () => {
    markStale()
    if (shareStore.token) scheduleShareSave()
  },
  { deep: true }
)

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
const messages = computed(() =>
  (result.value?.elements || [])
    .filter((r) => r.exclusion)
    .map((r) => ({
      id: r.id,
      title: r.title,
      text: r.exclusion || '',
      // АКЗ сюда не попадает: конструкция без огнезащиты считается без ошибки.
      short: r.exclusion?.startsWith('не задан предел')
        ? 'Не задан предел огнестойкости R'
        : 'Недостижимый предел при текущем δпр',
      color: RED
    }))
)
const totalLength = computed(() => {
  const own = (list: FormElement[]) => list.reduce((a, el) => a + (Number(el.lengthM) || 0) * (Number(el.quantity) || 0), 0)
  return own(form.ungrouped) + form.groups.reduce((a, g) => a + own(g.elements) * (Number(g.quantity) || 1), 0)
})
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
  if (shareNote.value) return shareNote.value
  if (stale.value) return 'Данные изменены после расчёта — пересчитайте'
  if (result.value) return `Расчёт выполнен · calcId ${result.value.id}`
  if (validation.value.count) return 'Заполните объект и отметьте согласие, чтобы рассчитать'
  return 'Готово к расчёту'
})
const barHintColor = computed(() =>
  store.error || (touched.value && validation.value.count) ? RED : stale.value ? ORANGE : exportMsg.value ? GREEN : 'var(--content-secondary-enabled)'
)
const barTitle = computed(() => {
  // Групп по умолчанию нет — тогда в строке итогов их и не упоминаем.
  const groupsPart = form.groups.length ? `${form.groups.length} гр. · ` : ''
  const base = `${groupsPart}${allElements.value.length} эл. · ${fmt(totalLength.value, 1)} м`
  return result.value ? `${base} · ${fmt(totals.value.area, 1)} м² огнезащиты` : base
})
</script>

<template>
  <div class="calc-page">
    <div v-if="store.loadingDicts" class="calc-state">Загрузка справочников…</div>
    <div v-else-if="store.dictsError" class="calc-state">
      <div class="calc-banner calc-banner_error"><TnIcon name="info" :size="20" /><span>{{ store.dictsError }}</span></div>
      <TnButton secondary size="md" @click="store.loadDicts()">Повторить</TnButton>
    </div>

    <div v-else-if="dicts" class="calc-layout" :class="{ 'calc-layout_single': !messages.length }">
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
          v-for="b in blocks"
          :key="b.ordinal"
          :class="{ 'calc-group-drop': dragOverBlock === b.ordinal }"
          @dragover.prevent="dragOverBlock = b.ordinal"
          @dragleave="dragOverBlock === b.ordinal && (dragOverBlock = null)"
          @drop.prevent="onDropToBlock(b.ordinal)"
        >
          <div class="calc-col">
            <!-- Панель группы: у конструкций без группы её нет — по умолчанию
                 на экране одна конструкция и ни одной группы. -->
            <div v-if="b.group" class="calc-group-head">
              <div style="flex: 1 1 auto; min-width: 160px">
                <TnInput v-model="b.group.title" label="Группа конструкций" :placeholder="`Группа ${b.ordinal}`" />
              </div>
              <div style="flex: 0 0 132px">
                <TnNumberInput :model-value="b.group.quantity" label="Кол-во групп" required integer @update:model-value="(v) => setGroupQuantity(b, v)" />
              </div>
              <div v-if="form.groups.length > 1 || b.elements.length > 1" style="flex: 0 0 120px">
                <TnSelect :model-value="b.group.groupHt === '' || b.group.groupHt === undefined ? '' : String(b.group.groupHt)" label="R для всех" placeholder="R…" :options="(dicts.selects.ht_level || [])" @update:model-value="(v) => setGroupHt(b, v)" />
              </div>
              <TnButton link icon="delete" @click="removeGroup(b.ordinal)">Удалить группу</TnButton>
            </div>

            <!-- Выбор способа заполнения — в области первой конструкции: пока
                 строки не пришли из распознавания, пользователь решает здесь,
                 заполнять конструкции вручную или распознать таблицу ИД. -->
            <div v-if="b.ordinal === firstFilledOrdinal && !prefillNote" class="calc-ocr-cta">
              <TnIcon name="info" :size="20" />
              <span>Конструкции можно заполнить вручную — или распознать таблицу ИД из PDF или скана спецификации, строки придут в эту форму.</span>
              <TnButton secondary size="md" @click="goRecognize">Распознать таблицу ИД</TnButton>
            </div>

            <div v-if="!b.elements.length" class="calc-group-empty">
              {{ b.group ? 'Группа пуста — добавьте элемент или перетащите его сюда из общего списка.' : 'Добавьте конструкцию — или перетащите сюда элемент из группы, чтобы вынести его из неё.' }}
            </div>

            <ElementCard
              v-for="(el, ei) in b.elements"
              :key="el._uid ?? ei"
              :el="el"
              :label="elementLabel(b.ordinal, ei)"
              :dicts="dicts"
              :result="resultFor(el)"
              :errors="shownErrors.elements[uidOf(el)]"
              :group-options="groupOptions"
              :group-index="blockOrdinalOf(el)"
              :draggable="blocks.length > 1"
              @copy="copyElement(b.ordinal, ei)"
              @remove="removeElement(b.ordinal, ei)"
              @move="(to) => moveElementTo(el, to)"
              @dragstart="(e) => onDragStart(el, e)"
            />

            <div><TnButton secondary size="md" icon="add" @click="addElement(b.ordinal)">Добавить элемент</TnButton></div>
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
                <div class="calc-msg-text"><span style="font-weight: var(--font-weight-accent)">{{ m.title }}</span> — <span style="color: var(--content-secondary-enabled)">{{ m.text }}</span></div>
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

      <!-- Боковая колонка: только сообщения расчёта; «Сводка» убрана (2026-09-23),
           её цифры и так есть в нижней панели и в ведомости -->
      <div v-if="messages.length" class="calc-side">
        <TnCard>
          <div class="calc-col-12">
            <div class="calc-h2">Требует внимания</div>
            <div v-for="m in messages" :key="m.id" class="calc-msg">
              <div class="calc-msg-dot" :style="{ background: m.color }" />
              <div class="calc-msg-text"><span style="font-weight: var(--font-weight-accent)">{{ m.title }}</span><br /><span style="color: var(--content-secondary-enabled)">{{ m.short }}</span></div>
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
      <TnButton v-if="shareStore.token" secondary size="md" icon="copy" @click="copyShareLink">Поделиться</TnButton>
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
