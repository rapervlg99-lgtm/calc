<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import TnCard from '../ui/TnCard.vue'
import TnButton from '../ui/TnButton.vue'
import TnInput from '../ui/TnInput.vue'
import TnNumberInput from '../ui/TnNumberInput.vue'
import TnSelect from '../ui/TnSelect.vue'
import TnSearchSelect from '../ui/TnSearchSelect.vue'
import TnCheckbox from '../ui/TnCheckbox.vue'
import TnIcon from '../ui/TnIcon.vue'
import SidesPicker from './SidesPicker.vue'
import type { DictsResponse, ElementInput, ElementResult, HeatedSides } from '../../types/api'
import { elementDisplayName } from '../../utils/constructionLabel'
import { fmt, resultDelta, resultOutput } from '../../utils/calcView'
import { assortmentLabel, LEGACY_STANDARD, rollsForShape, rollsForStandard, standardOptions } from '../../utils/rollCatalog'

/** `_uid` — клиентский идентификатор; в API уходит как id элемента, чтобы сопоставлять результаты. */
export type FormElement = ElementInput & { profileMiss?: boolean; _uid?: number }

const MANUAL = '__manual'

const props = defineProps<{
  el: FormElement
  label: string
  dicts: DictsResponse
  result?: ElementResult
  errors?: { length?: string; quantity?: string }
  groupOptions?: { value: string; label: string }[]
  groupIndex?: number
  draggable?: boolean
}>()
const emit = defineEmits<{
  (e: 'copy'): void
  (e: 'remove'): void
  (e: 'move', gi: number): void
  (e: 'dragstart', ev: DragEvent): void
}>()

/** Плоский список профилей в порядке словаря — без заголовков семейств (двутавр, швеллер…). */
const shapeOptions = computed(() =>
  props.dicts.profiles.flatMap((f) => f.shapes.map((s) => ({ value: s.id, label: s.label })))
)

function rollsFor(shape: string) {
  return rollsForShape(props.dicts.roll, shape)
}
const gostOptions = computed(() => standardOptions(rollsFor(props.el.shape)))
const gost = ref('')
watch(() => [props.el.shape, props.el.rollId, props.dicts.roll] as const, () => {
  const selected = props.dicts.roll.find((r) => r.id === props.el.rollId && r.shape === props.el.shape)
  if (selected) gost.value = selected.standard || LEGACY_STANDARD
  else if (!gostOptions.value.some((o) => o.value === gost.value)) gost.value = gostOptions.value[0]?.value || LEGACY_STANDARD
}, { immediate: true })
function onGost(value: string) {
  gost.value = value
  const selected = props.dicts.roll.find((r) => r.id === props.el.rollId && r.shape === props.el.shape)
  if (selected && (selected.standard || LEGACY_STANDARD) !== value) props.el.rollId = undefined
}
const rollOptions = computed(() => [
  { value: MANUAL, label: 'Ручные размеры' },
  ...rollsForStandard(rollsFor(props.el.shape), gost.value).map((r) => ({ value: r.id, label: assortmentLabel(r) }))
])
const rollValue = computed(() => props.el.rollId || MANUAL)
const manual = computed(() => !props.el.rollId)

function onRollPick(id: string) {
  if (id === MANUAL) {
    props.el.rollId = undefined
    if (!props.el.dims) props.el.dims = {}
    return
  }
  props.el.rollId = id
  const mark = rollsForStandard(rollsFor(props.el.shape), gost.value).find((r) => r.id === id)
  if (mark?.dims) props.el.dims = { ...mark.dims }
  if (mark?.shape) props.el.shape = mark.shape
  props.el.profileMiss = false
  if (mark?.label && !(props.el.title || '').trim()) {
    props.el.title = elementDisplayName(props.el.construction || '', mark.label)
  }
}
function onShape(id: string) {
  gost.value = ''
  props.el.shape = id
  // сортамент другого профиля больше не подходит
  if (props.el.rollId && !rollsFor(id).some((r) => r.id === props.el.rollId)) props.el.rollId = undefined
}

const picture = computed(() => {
  for (const f of props.dicts.profiles) for (const s of f.shapes) if (s.id === props.el.shape) return s.picture || s.id
  return props.el.shape
})

const isTaikor = computed(() => ['2', '3', '4'].includes(props.el.coat))
const isAkz = computed(() => props.el.coat === '1.5')
const isOzm = computed(() => props.el.coat === '1')

/** Смена покрытия: АКЗ — не огнезащита, предел огнестойкости для неё не нужен и
 *  не отправляется (0). Возврат к огнезащитному покрытию подставляет R, если он
 *  был сброшен, — иначе движок сообщит, что предел не задан. */
function onCoat(v: string) {
  props.el.coat = v
  if (v === '1.5') {
    props.el.htLevel = 0
    return
  }
  if (!props.el.htLevel) props.el.htLevel = Number(opts('ht_level')[0]?.value) || 60
}

const sidesCount = computed(() => (['top', 'right', 'bottom', 'left'] as (keyof HeatedSides)[]).filter((k) => props.el.sides[k]).length)
function toggleSide(k: keyof HeatedSides) {
  props.el.sides[k] = !props.el.sides[k]
}

function dim(k: string): number | null {
  const v = props.el.dims?.[k]
  return v === undefined ? null : v
}
function setDim(k: string, v: number | null) {
  if (!props.el.dims) props.el.dims = {}
  if (v === null) delete props.el.dims[k]
  else props.el.dims[k] = v
}

const opts = (key: string) => props.dicts.selects[key] || []
// «не задан» — законный выбор: предел огнестойкости нужен не каждой конструкции
// (у АКЗ его нет вовсе), а для огнезащитного покрытия движок скажет, что R не
// задан, вместо молчаливого нуля.
const htOptions = computed(() => [
  { value: '', label: 'не задан' },
  ...opts('ht_level').map((o) => ({ value: o.value, label: o.label }))
])
</script>

<template>
  <TnCard :padding="16" :radius="12" secondary :class="{ 'calc-el-miss': el.profileMiss }">
    <div class="calc-col-12">
      <div class="calc-el-head">
        <span v-if="draggable" class="calc-el-drag" draggable="true" title="Перетащите в другую группу" @dragstart="emit('dragstart', $event)">⠿</span>
        <div class="calc-el-label">{{ label }}</div>
        <div style="flex: 0 1 320px; min-width: 160px">
          <TnInput :model-value="el.title || ''" placeholder="Обозначение элемента" aria-label="Обозначение элемента" @update:model-value="(v) => (el.title = v)" />
        </div>
        <span v-if="el.profileMiss" class="calc-miss-badge">профиль не найден</span>
        <div class="calc-grow" />
        <div v-if="result" class="calc-el-live">δ<small>пр</small> <b>{{ fmt(result.dpr, 2) }}</b> мм</div>
        <div v-if="groupOptions && groupOptions.length > 1" class="calc-move-select">
          <TnSelect :model-value="String(groupIndex ?? 0)" :options="groupOptions" aria-label="Перенести в группу" @update:model-value="(v) => emit('move', Number(v))" />
        </div>
        <TnButton link icon="copy" title="Дублировать элемент" @click="emit('copy')" />
        <TnButton link icon="delete" title="Удалить элемент" @click="emit('remove')" />
      </div>

      <p v-if="el.profileMiss" class="calc-note calc-note_warn">
        <TnIcon name="info" :size="20" />
        <span>Марка «{{ el.title }}» не сопоставлена со справочником — выберите профиль и сортамент ГОСТ.</span>
      </p>

      <div class="calc-el-body">
        <SidesPicker :sides="el.sides" :picture="picture" :caption="`${sidesCount} из 4 сторон`" @toggle="toggleSide" />

        <div class="calc-el-fields">
          <div class="calc-grid-4">
            <TnSelect label="Профиль" required :model-value="el.shape" :options="shapeOptions" @update:model-value="onShape" />
            <TnSelect label="ГОСТ" :model-value="gost" :options="gostOptions" @update:model-value="onGost" />
            <TnSearchSelect label="Сортамент" :model-value="rollValue" :options="rollOptions" search-placeholder="Найти марку" @update:model-value="onRollPick" />
            <TnSelect label="Тип конструкции" required :model-value="el.frType" :options="opts('fr_type')" @update:model-value="(v) => (el.frType = v)" />
            <!-- Предел огнестойкости не обязателен: у АКЗ его нет вовсе (поле
                 скрыто), у огнезащитного покрытия «не задан» — это осознанный
                 выбор, движок сообщит о нём отдельной строкой. -->
            <TnSelect v-if="!isAkz" label="Предел огнестойкости R" :model-value="el.htLevel ? String(el.htLevel) : ''" :options="htOptions" @update:model-value="(v) => (el.htLevel = v === '' ? 0 : Number(v))" />
          </div>

          <div v-if="manual" class="calc-grid-5">
            <TnNumberInput label="h, мм" :model-value="dim('h')" @update:model-value="(v) => setDim('h', v)" />
            <TnNumberInput label="b, мм" :model-value="dim('b')" @update:model-value="(v) => setDim('b', v)" />
            <TnNumberInput label="s, мм" :model-value="dim('s')" @update:model-value="(v) => setDim('s', v)" />
            <TnNumberInput label="t, мм" :model-value="dim('t')" @update:model-value="(v) => setDim('t', v)" />
            <TnNumberInput label="R, мм" :model-value="dim('R')" @update:model-value="(v) => setDim('R', v)" />
            <TnNumberInput v-if="el.shape === 'channel_unequal'" label="b₁, мм" :model-value="dim('b1')" @update:model-value="(v) => setDim('b1', v)" />
          </div>

          <div class="calc-grid-4">
            <TnNumberInput label="Длина, м" required :model-value="el.lengthM" :error="errors?.length" @update:model-value="(v) => (el.lengthM = v ?? 0)" />
            <TnNumberInput label="Количество, шт" required integer :model-value="el.quantity" :error="errors?.quantity" @update:model-value="(v) => (el.quantity = v ?? 0)" />
            <TnSelect label="Покрытие" required :model-value="el.coat" :options="opts('fr_coat')" @update:model-value="onCoat" />
            <TnSelect v-if="isOzm" label="Метод нанесения" required :model-value="el.method" :options="opts('fr_method')" @update:model-value="(v) => (el.method = v)" />
          </div>

          <div v-if="isOzm" class="calc-flags">
            <TnCheckbox :model-value="!!el.decor" label="Декоративное покрытие Ceresit" @update:model-value="(v) => (el.decor = v)" />
          </div>
          <div v-if="isTaikor" class="calc-flags">
            <TnCheckbox :model-value="!!el.primer" label="TAIKOR Primer 150" @update:model-value="(v) => (el.primer = v)" />
            <TnCheckbox :model-value="!!el.enamel" label="TAIKOR Top 425 (финишная эмаль)" @update:model-value="(v) => (el.enamel = v)" />
          </div>
          <div v-if="isAkz" class="calc-note">
            <TnIcon name="info" :size="20" />
            <span>АКЗ — только антикоррозионная защита: конструкция входит в расчёт со своей площадью, огнезащитный материал для неё не считается, предел огнестойкости не нужен.</span>
          </div>

          <div v-if="result" class="calc-el-result">
            <span>δпр <b>{{ fmt(result.dpr, 2) }} мм</b></span>
            <span>δ <b>{{ resultDelta(result) }}{{ result.exclusion || isAkz ? '' : ' мм' }}</b></span>
            <span>S <b>{{ fmt(result.areaM2, 2) }} м²</b></span>
            <span>Расход <b>{{ resultOutput(result) }}</b></span>
            <span v-if="result.exclusion" class="calc-note" :class="isAkz ? 'calc-note_warn' : 'calc-note_error'" style="width: 100%">
              <TnIcon name="info" :size="20" />
              <span>{{ result.exclusion }}</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  </TnCard>
</template>
