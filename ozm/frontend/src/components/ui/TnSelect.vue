<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import TnIcon from './TnIcon.vue'

export interface TnSelectOption { value: string; label: string }
export interface TnSelectGroup { label: string; options: TnSelectOption[] }

/**
 * Выпадающий список TN Life (uikit/select) — один облик для всех полей выбора
 * калькулятора, такой же, как у «Сортамента ГОСТ»: поле-триггер, список
 * `tn-select__wrapper-desktop` с отметкой выбранного, при длинном списке — строка
 * поиска. Список рисуется через Teleport с фиксированными координатами под полем,
 * поэтому не раздвигает карточку и ложится поверх полей ниже; если места снизу
 * мало — раскрывается вверх. Клавиатура: Enter/Space/↓ открыть, ↑/↓ ходить,
 * Enter выбрать, Esc/Tab закрыть.
 */
const props = withDefaults(
  defineProps<{
    modelValue?: string | number | null
    options?: TnSelectOption[]
    groups?: TnSelectGroup[]
    label?: string
    description?: string
    placeholder?: string
    size?: 's' | 'm'
    required?: boolean
    disabled?: boolean
    error?: string
    ariaLabel?: string
    /** Строка поиска в списке; по умолчанию — когда вариантов от 8 */
    searchable?: boolean
    searchPlaceholder?: string
    emptyHint?: string
  }>(),
  { modelValue: '', options: () => [], placeholder: 'Выберите', size: 's', searchable: undefined,
    searchPlaceholder: 'Найти', emptyHint: 'Ничего не найдено' }
)
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const MAX_RENDER = 300
const SEARCH_FROM = 8
const id = useId()
const listId = `${id}-list`
const open = ref(false)
const query = ref('')
const active = ref(-1)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLElement | null>(null)
const search = ref<HTMLInputElement | null>(null)
const listEl = ref<HTMLElement | null>(null)
const listStyle = ref<Record<string, string>>({})

const value = computed(() => (props.modelValue === null || props.modelValue === undefined ? '' : String(props.modelValue)))

/** Плоский список для отрисовки: заголовки групп и варианты. */
interface Row { kind: 'group' | 'option'; label: string; value: string; index: number }
const flat = computed<Row[]>(() => {
  const out: Row[] = []
  let i = 0
  if (props.groups && props.groups.length) {
    for (const g of props.groups) {
      out.push({ kind: 'group', label: g.label, value: '', index: -1 })
      for (const o of g.options) out.push({ kind: 'option', label: o.label, value: o.value, index: i++ })
    }
  } else {
    for (const o of props.options) out.push({ kind: 'option', label: o.label, value: o.value, index: i++ })
  }
  return out
})
const allOptions = computed(() => flat.value.filter((r) => r.kind === 'option'))
const selected = computed(() => allOptions.value.find((o) => o.value === value.value))
const hasSearch = computed(() => props.searchable ?? allOptions.value.length >= SEARCH_FROM)

/** Поиск без учёта регистра и пробелов: «20Б1» находит «20 Б1». */
const norm = (s: string) => s.toLowerCase().replace(/\s+/g, '')
const filtered = computed<Row[]>(() => {
  const q = norm(query.value)
  if (!q) return flat.value
  const out: Row[] = []
  let pendingGroup: Row | null = null
  for (const r of flat.value) {
    if (r.kind === 'group') { pendingGroup = r; continue }
    if (norm(r.label).includes(q)) {
      if (pendingGroup) { out.push(pendingGroup); pendingGroup = null }
      out.push(r)
    }
  }
  return out
})
const visible = computed(() => {
  const rows: Row[] = []
  let n = 0
  for (const r of filtered.value) {
    if (r.kind === 'option') { if (n >= MAX_RENDER) break; n++ }
    rows.push(r)
  }
  return rows
})
const truncated = computed(() => filtered.value.filter((r) => r.kind === 'option').length - visible.value.filter((r) => r.kind === 'option').length)
const visibleOptions = computed(() => visible.value.filter((r) => r.kind === 'option'))

function place(): void {
  const el = trigger.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const below = window.innerHeight - r.bottom
  const above = r.top
  const style: Record<string, string> = {
    position: 'fixed', left: `${r.left}px`, width: `${r.width}px`, zIndex: '1300'
  }
  if (below < 260 && above > below) {
    style.bottom = `${window.innerHeight - r.top + 4}px`
    style.maxHeight = `${Math.min(350, above - 8)}px`
  } else {
    style.top = `${r.bottom + 4}px`
    style.maxHeight = `${Math.min(350, below - 8)}px`
  }
  listStyle.value = style
}

function onDocDown(e: MouseEvent) {
  const t = e.target as Node
  if (root.value?.contains(t) || listEl.value?.contains(t)) return
  close()
}

async function show() {
  if (props.disabled || open.value) return
  open.value = true
  query.value = ''
  active.value = selected.value ? visibleOptions.value.findIndex((o) => o.value === selected.value!.value) : -1
  place()
  document.addEventListener('mousedown', onDocDown)
  window.addEventListener('scroll', place, true)
  window.addEventListener('resize', place)
  await nextTick()
  if (hasSearch.value) search.value?.focus()
  scrollActiveIntoView()
}

function close() {
  if (!open.value) return
  open.value = false
  document.removeEventListener('mousedown', onDocDown)
  window.removeEventListener('scroll', place, true)
  window.removeEventListener('resize', place)
}

function toggle() {
  if (open.value) close()
  else void show()
}

function pick(v: string) {
  emit('update:modelValue', v)
  close()
  trigger.value?.focus()
}

function move(delta: number) {
  const n = visibleOptions.value.length
  if (!n) return
  if (!open.value) { void show(); return }
  active.value = ((active.value + delta) % n + n) % n
  scrollActiveIntoView()
}

function scrollActiveIntoView() {
  const opt = visibleOptions.value[active.value]
  if (!opt || !listEl.value) return
  const el = listEl.value.querySelector<HTMLElement>(`[data-value="${CSS.escape(opt.value)}"]`)
  el?.scrollIntoView({ block: 'nearest' })
}

function onEnter() {
  if (!open.value) { void show(); return }
  const opt = visibleOptions.value[active.value]
  if (opt) pick(opt.value)
  else if (visibleOptions.value.length === 1) pick(visibleOptions.value[0].value)
}

watch(() => props.disabled, (d) => { if (d) close() })
watch(query, () => { active.value = visibleOptions.value.length ? 0 : -1 })
onBeforeUnmount(close)
</script>

<template>
  <div ref="root" class="tn-select" :class="{ 'tn-select_required': required }">
    <label v-if="label" :id="`${id}-label`" class="tn-select__label" @click="trigger?.focus()">{{ label }}</label>
    <p v-if="description" class="tn-select__description">{{ description }}</p>
    <div style="position: relative">
      <div
        :id="id"
        ref="trigger"
        class="tn-select__inner-input"
        :class="[
          size === 'm' && 'tn-select__inner-input_medium',
          open && 'tn-select__inner-input_open',
          disabled && 'tn-select__inner-input_disabled',
          error && 'tn-select__inner-input_error'
        ]"
        role="combobox"
        :aria-expanded="open"
        :aria-controls="listId"
        :aria-labelledby="label ? `${id}-label` : undefined"
        :aria-label="ariaLabel"
        :aria-disabled="disabled || undefined"
        :tabindex="disabled ? -1 : 0"
        @click="toggle"
        @keydown.enter.prevent="onEnter"
        @keydown.space.prevent="toggle"
        @keydown.down.prevent="move(1)"
        @keydown.up.prevent="move(-1)"
        @keydown.escape="close"
        @keydown.tab="close"
      >
        <span class="tn-select__inner-input-placeholder" :class="{ 'tn-select__inner-input-placeholder_main': selected }">
          {{ selected ? selected.label : placeholder }}
        </span>
      </div>
      <button type="button" class="tn-select__inner-arrow" :class="{ 'tn-select__inner-arrow_open': open }" tabindex="-1" :disabled="disabled" @click="toggle">
        <TnIcon name="down-s" :size="20" />
      </button>
      <Teleport to="body">
        <div
          v-if="open"
          :id="listId"
          ref="listEl"
          class="tn-select__wrapper-desktop tn-select__wrapper-desktop_floating"
          :class="{ 'tn-select__wrapper-desktop_search': hasSearch }"
          role="listbox"
          :style="listStyle"
        >
          <div v-if="hasSearch" class="tn-select__wrapper-desktop-input-wrapper">
            <input
              ref="search"
              v-model="query"
              class="tn-input__inner-input tn-input__inner-input_size-s"
              type="text"
              :placeholder="searchPlaceholder"
              @keydown.down.prevent="move(1)"
              @keydown.up.prevent="move(-1)"
              @keydown.enter.prevent="onEnter"
              @keydown.escape="close"
              @keydown.tab="close"
            />
          </div>
          <ul class="tn-select__flat-list-container">
            <template v-for="(r, i) in visible" :key="r.kind === 'group' ? `g:${r.label}:${i}` : r.value">
              <li v-if="r.kind === 'group'" class="tn-select__group-label" role="presentation">{{ r.label }}</li>
              <li
                v-else
                class="tn-select__flat-list-item"
                :class="{ 'tn-select__flat-list-item_selected': r.value === value, 'tn-select__flat-list-item_active': visibleOptions[active]?.value === r.value }"
                role="option"
                :aria-selected="r.value === value"
                :data-value="r.value"
                @mouseenter="active = visibleOptions.findIndex((o) => o.value === r.value)"
                @click="pick(r.value)"
              >
                <span class="tn-select__flat-list-title">{{ r.label }}</span>
                <TnIcon v-if="r.value === value" name="check" :size="20" />
              </li>
            </template>
          </ul>
          <p v-if="!visibleOptions.length" class="tn-select__empty-list-hint">{{ emptyHint }}</p>
          <p v-else-if="truncated > 0" class="tn-select__empty-list-hint">Ещё {{ truncated }} — уточните запрос</p>
        </div>
      </Teleport>
    </div>
    <p v-if="error" class="tn-select__message tn-select__message_error">{{ error }}</p>
  </div>
</template>

<style>
/* Список вне потока документа (Teleport в body): не раздвигает карточку,
   ложится поверх полей ниже; тень — как у всплывающих меню кита. */
.tn-select__wrapper-desktop_floating {
  box-shadow: var(--shadow-large);
  border: 1px solid var(--border-secondary-enabled);
}

.tn-select__flat-list-item_active {
  background-color: var(--background-secondary-a-enabled);
}

.tn-select__group-label {
  padding: 10px 12px 4px;
  font-size: var(--font-size-label-medium);
  line-height: var(--font-lineHeight-label-medium);
  font-weight: var(--font-weight-accent);
  color: var(--content-secondary-enabled);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  cursor: default;
}

.tn-select__inner-input {
  cursor: pointer;
}
</style>
