<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import TnIcon from './TnIcon.vue'
import type { TnSelectOption } from './TnSelect.vue'

/**
 * Выпадающий список с поиском (uikit/select searchable): для длинных
 * справочников вроде сортамента ГОСТ. Список отрисовывается в стиле
 * tn-select__wrapper-desktop, первые MAX_RENDER совпадений.
 */
const props = withDefaults(
  defineProps<{
    modelValue?: string | null
    options: TnSelectOption[]
    label?: string
    placeholder?: string
    searchPlaceholder?: string
    size?: 's' | 'm'
    required?: boolean
    disabled?: boolean
    error?: string
    emptyHint?: string
  }>(),
  { modelValue: '', placeholder: 'Выберите', searchPlaceholder: 'Найти', size: 's', emptyHint: 'Ничего не найдено' }
)
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const MAX_RENDER = 300
const open = ref(false)
const query = ref('')
const root = ref<HTMLElement | null>(null)
const search = ref<HTMLInputElement | null>(null)

const selected = computed(() => props.options.find((o) => o.value === (props.modelValue ?? '')))
const list = computed(() => {
  const q = query.value.trim().toLowerCase()
  const src = q ? props.options.filter((o) => o.label.toLowerCase().includes(q)) : props.options
  return src.slice(0, MAX_RENDER)
})
const truncated = computed(() => {
  const q = query.value.trim().toLowerCase()
  const total = q ? props.options.filter((o) => o.label.toLowerCase().includes(q)).length : props.options.length
  return total - list.value.length
})

function onDocDown(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) close()
}
async function toggle() {
  if (props.disabled) return
  open.value = !open.value
  if (open.value) {
    query.value = ''
    document.addEventListener('mousedown', onDocDown)
    await nextTick()
    search.value?.focus()
  } else {
    document.removeEventListener('mousedown', onDocDown)
  }
}
function close() {
  open.value = false
  document.removeEventListener('mousedown', onDocDown)
}
function pick(v: string) {
  emit('update:modelValue', v)
  close()
}
watch(() => props.disabled, (d) => { if (d) close() })
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocDown))
</script>

<template>
  <div ref="root" class="tn-select" :class="{ 'tn-select_required': required }">
    <p v-if="label" class="tn-select__label">{{ label }}</p>
    <div style="position: relative">
      <div
        class="tn-select__inner-input"
        :class="[
          size === 'm' && 'tn-select__inner-input_medium',
          open && 'tn-select__inner-input_open',
          disabled && 'tn-select__inner-input_disabled',
          error && 'tn-select__inner-input_error'
        ]"
        role="combobox"
        :aria-expanded="open"
        tabindex="0"
        @click="toggle"
        @keydown.enter.prevent="toggle"
        @keydown.escape="close"
      >
        <span class="tn-select__inner-input-placeholder" :class="{ 'tn-select__inner-input-placeholder_main': selected }">
          {{ selected ? selected.label : placeholder }}
        </span>
      </div>
      <button type="button" class="tn-select__inner-arrow" :class="{ 'tn-select__inner-arrow_open': open }" tabindex="-1" @click="toggle">
        <TnIcon name="down-s" :size="20" />
      </button>
      <div v-if="open" class="tn-select__wrapper-desktop">
        <div class="tn-select__wrapper-desktop-input-wrapper">
          <input
            ref="search"
            v-model="query"
            class="tn-input__inner-input tn-input__inner-input_size-s"
            type="text"
            :placeholder="searchPlaceholder"
            @keydown.escape="close"
          />
        </div>
        <ul class="tn-select__flat-list-container">
          <li
            v-for="o in list"
            :key="o.value"
            class="tn-select__flat-list-item"
            :class="{ 'tn-select__flat-list-item_selected': o.value === (modelValue ?? '') }"
            @click="pick(o.value)"
          >
            <span class="tn-select__flat-list-title">{{ o.label }}</span>
            <TnIcon v-if="o.value === (modelValue ?? '')" name="check" :size="20" />
          </li>
        </ul>
        <p v-if="!list.length" class="tn-select__empty-list-hint">{{ emptyHint }}</p>
        <p v-else-if="truncated > 0" class="tn-select__empty-list-hint">Ещё {{ truncated }} — уточните запрос</p>
      </div>
    </div>
    <p v-if="error" class="tn-select__message tn-select__message_error">{{ error }}</p>
  </div>
</template>
