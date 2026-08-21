<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useCalcStore } from '../stores/calc'
import { usePrefillStore } from '../stores/prefill'
import { elementDisplayName } from '../utils/constructionLabel'
import { mapPrefillPayload } from '../utils/prefillMapper'
import type { ElementInput, ElementResult, GroupInput } from '../types/api'

type FormElement = ElementInput & { profileMiss?: boolean }
type FormGroup = { title: string; elements: FormElement[] }

const store = useCalcStore()
const prefillStore = usePrefillStore()
const router = useRouter()
const prefillNote = ref('')

function emptyElement(): FormElement {
  return {
    title: '',
    shape: 'I-beam_',
    dims: { h: 100, b: 55, s: 4.1, t: 5.7, R: 7 },
    frType: '1',
    htLevel: 15,
    sides: { left: true, top: true, right: true, bottom: true },
    lengthM: 1,
    quantity: 1,
    coat: '1',
    method: '1',
    primer: false,
    enamel: false,
    decor: true
  }
}

const form = reactive({
  objectName: 'Объект',
  address: '—',
  consent: true,
  useGroups: false,
  frDurability: '1',
  paramMode: 'gost' as 'gost' | 'manual',
  groups: [{ title: '', elements: [emptyElement()] }] as FormGroup[]
})

function flatIndex(gi: number, ei: number): number {
  let n = 0
  for (let i = 0; i < gi; i++) n += form.groups[i]?.elements.length ?? 0
  return n + ei
}

function applyPendingPrefill() {
  const payload = prefillStore.consume()
  if (!payload) return
  const mapped = mapPrefillPayload(payload, store.dicts?.roll || [])
  if (!mapped.elements.length) {
    prefillNote.value = 'Prefill пуст — элементы не изменены'
    return
  }
  form.groups = mapped.groups.map((g) => ({
    title: g.title,
    elements: g.elements.map((m) => ({
      ...m.element,
      profileMiss: m.profileMiss
    }))
  }))
  form.useGroups = mapped.useGroups
  const misses = mapped.elements.filter((m) => m.profileMiss).length
  const hits = mapped.elements.length - misses
  const groupNote = mapped.useGroups
    ? `, групп: ${mapped.groups.filter((g) => g.title).length}`
    : ''
  prefillNote.value = misses
    ? `Предзаполнено ${mapped.elements.length} эл.${groupNote} (${hits} с маркой из справочника, ${misses} — выберите профиль вручную)`
    : `Предзаполнено ${mapped.elements.length} эл. из OCR${groupNote}, марки найдены в справочнике`
  void recalc()
}

onMounted(async () => {
  await store.loadDicts()
  applyPendingPrefill()
  if (!prefillNote.value) await recalc()
})

const shapeOptions = computed(() => {
  const out: { value: string; label: string; picture?: string }[] = []
  for (const f of store.dicts?.profiles || []) {
    for (const s of f.shapes) {
      out.push({ value: s.id, label: s.label.toUpperCase(), picture: s.picture || s.id })
    }
  }
  return out
})

function rollsFor(shape: string) {
  return (store.dicts?.roll || [])
    .filter(r => {
      if (!r.shape) return true
      const base = shape.replace(/_$/, '')
      return r.shape === shape || r.shape.startsWith(base) || shape.startsWith(r.shape.replace(/_$/, ''))
    })
    .slice(0, 400)
}

function onRollPick(el: FormElement, rollId: string) {
  el.rollId = rollId
  const mark = store.dicts?.roll.find(r => r.id === rollId)
  if (mark?.dims) el.dims = { ...mark.dims }
  if (mark?.shape) el.shape = mark.shape
  el.profileMiss = false
  if (mark?.label) {
    el.title = elementDisplayName(el.construction || '', mark.label)
  }
}

function profileImg(shape: string) {
  const pic = shapeOptions.value.find(s => s.value === shape)?.picture || shape
  return `/img/roll/${pic}.svg`
}

function elementHeading(el: FormElement, flatEi: number): string {
  const title = (el.title || '').trim()
  if (title) return title
  return elementDisplayName(el.construction || '', '', `Элемент ${flatEi + 1}`)
}

function addElement() {
  const last = form.groups[form.groups.length - 1]
  if (last) last.elements.push(emptyElement())
  else form.groups.push({ title: '', elements: [emptyElement()] })
}
function copyElement(gi: number, ei: number) {
  const src = form.groups[gi]?.elements[ei]
  if (!src) return
  const clone: FormElement = structuredClone(src)
  delete clone.id
  form.groups[gi].elements.splice(ei + 1, 0, clone)
}
function removeElement(gi: number, ei: number) {
  const g = form.groups[gi]
  if (!g) return
  if (form.groups.reduce((n, x) => n + x.elements.length, 0) <= 1) return
  g.elements.splice(ei, 1)
  if (g.elements.length === 0 && form.groups.length > 1) {
    form.groups.splice(gi, 1)
  }
}

function coatLabel(v: string) {
  return store.dicts?.selects.fr_coat.find(o => o.value === v)?.label || v
}

function resultFor(flatIdx: number): ElementResult | undefined {
  return store.result?.elements?.[flatIdx]
}

function mapEl(el: FormElement, i: number): ElementInput {
  return {
    ...el,
    title: el.title || `Элемент ${i + 1}`,
    method: el.coat === '1' ? el.method : '0'
  }
}

function buildCalcGroups(): GroupInput[] {
  if (!form.useGroups) {
    const elements = form.groups.flatMap((g) => g.elements).map(mapEl)
    return [{ title: '', quantity: 1, elements }]
  }
  const titled = form.groups.filter((g) => g.elements.length)
  if (titled.some((g) => g.title)) {
    return titled.map((g) => ({
      title: g.title,
      quantity: 1,
      elements: g.elements.map(mapEl)
    }))
  }
  return [{
    title: 'Группа 1',
    quantity: 1,
    elements: form.groups.flatMap((g) => g.elements).map(mapEl)
  }]
}

let timer: ReturnType<typeof setTimeout> | null = null
async function recalc() {
  if (!form.consent) return
  await store.calculate({
    objectName: form.objectName || 'Объект',
    address: form.address || '—',
    consent: true,
    frDurability: form.frDurability,
    groups: buildCalcGroups()
  })
}
function scheduleRecalc() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { void recalc() }, 350)
}

watch(form, () => scheduleRecalc(), { deep: true })

watch(
  () => form.useGroups,
  (on) => {
    if (!on) return
    if (form.groups.length === 1 && !form.groups[0].title) {
      form.groups[0].title = 'Группа 1'
    }
  }
)

async function download(fmt: 'pdf' | 'xlsx' | 'docx') {
  if (!store.result?.id) await recalc()
  await store.download(fmt)
}
</script>

<template>
  <div class="ozm-page">
    <div class="ozm-top">
      <h1 class="ozm-title">Металлические конструкции</h1>
      <div class="ozm-top-actions">
        <button class="btn-primary" type="button" @click="router.push('/recognize')">
          Распознать таблицу ИД
        </button>
        <label class="ozm-group-toggle">
          <input type="checkbox" v-model="form.useGroups" />
          Сформировать группу элементов?
        </label>
      </div>
    </div>

    <p v-if="prefillNote" class="prefill-banner">{{ prefillNote }}</p>

    <div v-if="store.loadingDicts" class="muted">Загрузка справочников…</div>
    <div v-else-if="store.dictsError" class="error">{{ store.dictsError }}</div>

    <template v-else-if="store.dicts">
      <div class="field" style="max-width:640px">
        <label class="field-label">Степень огнестойкости проектируемого здания</label>
        <select class="field-control" v-model="form.frDurability">
          <option v-for="o in store.dicts.selects.fr_durability" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </div>

      <div class="meta-block">
        <div class="field">
          <label class="field-label">Наименование объекта</label>
          <input class="field-control" v-model="form.objectName" />
        </div>
        <div class="field">
          <label class="field-label">Адрес</label>
          <input class="field-control" v-model="form.address" />
        </div>
      </div>

      <template v-for="(g, gi) in form.groups" :key="gi">
        <h2 v-if="form.useGroups && g.title" class="ozm-group-heading">{{ g.title }}</h2>

        <article
          class="el"
          v-for="(el, ei) in g.elements"
          :key="`${gi}-${ei}`"
          :class="{ 'el-miss': el.profileMiss }"
        >
          <div class="el-head">
            <div class="el-title">
              {{ elementHeading(el, flatIndex(gi, ei)) }}
              <span v-if="el.profileMiss" class="miss-badge">профиль не найден</span>
            </div>
            <div class="el-head-actions">
              <button class="el-del" type="button" @click="copyElement(gi, ei)">Копировать</button>
              <button class="el-del" type="button" @click="removeElement(gi, ei)">Удалить ✕</button>
            </div>
          </div>
          <p v-if="el.profileMiss" class="miss-hint">
            Марка «{{ el.title }}» не сопоставлена со справочником — выберите тип и ГОСТ-профиль ниже.
          </p>

          <div class="el-form">
            <!-- LEFT -->
            <div class="el-left">
              <div class="field">
                <label class="field-label">Тип конструкции</label>
                <select class="field-control" v-model="el.frType">
                  <option v-for="o in store.dicts.selects.fr_type" :key="o.value" :value="o.value">{{ o.label }}</option>
                </select>
              </div>
              <div class="field">
                <label class="field-label">Требуемый предел огнестойкости</label>
                <select class="field-control" v-model.number="el.htLevel">
                  <option v-for="o in store.dicts.selects.ht_level" :key="o.value" :value="Number(o.value)">{{ o.label }}</option>
                </select>
              </div>
              <div class="field">
                <label class="field-label">Профиль</label>
                <select class="field-control" v-model="el.shape">
                  <option v-for="s in shapeOptions" :key="s.value" :value="s.value">{{ s.label }}</option>
                </select>
              </div>
              <div class="field">
                <label class="field-label">Параметры</label>
                <select class="field-control" v-model="form.paramMode">
                  <option value="gost">По ГОСТ</option>
                  <option value="manual">Вручную</option>
                </select>
              </div>
              <div class="field" v-if="form.paramMode === 'gost'">
                <label class="field-label">Номер (сортамент)</label>
                <select class="field-control" :value="el.rollId || ''" @change="onRollPick(el, ($event.target as HTMLSelectElement).value)">
                  <option value="">— выберите —</option>
                  <option v-for="r in rollsFor(el.shape)" :key="r.id" :value="r.id">{{ r.label || r.id }}</option>
                </select>
              </div>
              <div class="field-row-2">
                <div class="field">
                  <label class="field-label">Длина, м</label>
                  <input class="field-control" type="number" step="0.1" v-model.number="el.lengthM" />
                </div>
                <div class="field">
                  <label class="field-label">Количество</label>
                  <input class="field-control" type="number" step="1" v-model.number="el.quantity" />
                </div>
              </div>
            </div>

            <!-- RIGHT -->
            <div class="el-side">
              <div class="el-subtitle">Стороны обогрева</div>
              <div class="heat">
                <div class="heat-diagram">
                  <button type="button" class="heat-btn top" :class="{ on: el.sides.top }" @click="el.sides.top = !el.sides.top">∨∨</button>
                  <button type="button" class="heat-btn left" :class="{ on: el.sides.left }" @click="el.sides.left = !el.sides.left">›</button>
                  <div class="center">
                    <img :src="profileImg(el.shape)" :alt="el.shape" />
                  </div>
                  <button type="button" class="heat-btn right" :class="{ on: el.sides.right }" @click="el.sides.right = !el.sides.right">‹</button>
                  <button type="button" class="heat-btn bottom" :class="{ on: el.sides.bottom }" @click="el.sides.bottom = !el.sides.bottom">∧∧</button>
                </div>
                <div class="heat-dims">
                  <div class="field">
                    <label class="field-label">Высота (h), мм</label>
                    <input class="field-control" type="number" step="0.1" v-model.number="el.dims!.h" :disabled="form.paramMode==='gost' && !!el.rollId" />
                  </div>
                  <div class="field">
                    <label class="field-label">Ширина полок (b), мм</label>
                    <input class="field-control" type="number" step="0.1" v-model.number="el.dims!.b" :disabled="form.paramMode==='gost' && !!el.rollId" />
                  </div>
                  <div class="field">
                    <label class="field-label">Толщина стенки (s), мм</label>
                    <input class="field-control" type="number" step="0.1" v-model.number="el.dims!.s" :disabled="form.paramMode==='gost' && !!el.rollId" />
                  </div>
                  <div class="field">
                    <label class="field-label">Толщина полок (t), мм</label>
                    <input class="field-control" type="number" step="0.1" v-model.number="el.dims!.t" :disabled="form.paramMode==='gost' && !!el.rollId" />
                  </div>
                  <div class="field">
                    <label class="field-label">Радиус сопряжения (R), мм</label>
                    <input class="field-control" type="number" step="0.1" v-model.number="el.dims!.R" :disabled="form.paramMode==='gost' && !!el.rollId" />
                  </div>
                </div>
              </div>

              <div class="el-subtitle">Тип защитного покрытия</div>
              <div class="coat-grid">
                <div class="coat-pill" v-for="o in store.dicts.selects.fr_coat" :key="o.value">
                  <input :id="`coat-${gi}-${ei}-${o.value}`" type="radio" :value="o.value" v-model="el.coat" />
                  <label :for="`coat-${gi}-${ei}-${o.value}`">{{ o.label }}</label>
                </div>
              </div>

              <div class="field" v-if="el.coat === '1'">
                <label class="field-label">Метод</label>
                <select class="field-control" v-model="el.method">
                  <option v-for="o in store.dicts.selects.fr_method" :key="o.value" :value="o.value">{{ o.label }}</option>
                </select>
              </div>

              <label class="decor-check" v-if="el.coat === '1'">
                <input type="checkbox" v-model="el.decor" />
                Декоративное покрытие Ceresit
              </label>
              <div class="field-row-2" v-if="el.coat !== '1' && el.coat !== '1.5'" style="margin-bottom:14px">
                <label class="decor-check"><input type="checkbox" v-model="el.primer" /> Primer 150</label>
                <label class="decor-check"><input type="checkbox" v-model="el.enamel" /> Top 425</label>
              </div>

              <div class="el-total" v-if="resultFor(flatIndex(gi, ei))">
                <div>ПТМ:<span class="value">{{ String(resultFor(flatIndex(gi, ei))!.dpr).replace('.', ',') }} мм</span></div>
                <div>{{ coatLabel(el.coat) }}</div>
                <div>Площадь:<span class="value">{{ String(resultFor(flatIndex(gi, ei))!.areaM2).replace('.', ',') }} м²</span></div>
                <div>Необходимая толщина:<span class="value">{{ resultFor(flatIndex(gi, ei))!.delta }} мм</span></div>
                <div class="warn" v-if="resultFor(flatIndex(gi, ei))!.exclusion">{{ resultFor(flatIndex(gi, ei))!.exclusion }}</div>
              </div>
              <div class="muted" v-else>Считаем…</div>
            </div>
          </div>
        </article>
      </template>

      <div class="page-actions">
        <button class="btn-add" type="button" @click="addElement"><span class="plus">+</span>Добавить элемент</button>
        <button class="btn-ghost" type="button" @click="download('xlsx')">Excel</button>
        <button class="btn-ghost" type="button" @click="download('pdf')">PDF</button>
        <button class="btn-ghost" type="button" @click="download('docx')">Word</button>
      </div>
      <p v-if="store.error" class="error">{{ store.error }}</p>
    </template>
  </div>
</template>
