<script setup lang="ts">
import { ref, watch } from 'vue'
import TnInput from './TnInput.vue'

/**
 * Числовое поле поверх TnInput: пока пользователь печатает, храним строку
 * (иначе «4.» превращалось бы в 4), наружу отдаём число, как только оно валидно.
 */
const props = withDefaults(
  defineProps<{
    modelValue?: number | null
    label?: string
    placeholder?: string
    size?: 's' | 'm'
    required?: boolean
    disabled?: boolean
    error?: string
    integer?: boolean
    ariaLabel?: string
  }>(),
  { modelValue: null, size: 's', integer: false }
)
const emit = defineEmits<{ (e: 'update:modelValue', v: number | null): void }>()

const text = ref(format(props.modelValue))
let focusedValue: string | null = null

function format(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return ''
  return String(v).replace('.', ',')
}

watch(
  () => props.modelValue,
  (v) => {
    // Не перетираем ввод пользователя, пока он печатает то же число.
    const parsed = parse(text.value)
    if (parsed !== v || focusedValue === null) text.value = format(v)
  }
)

function parse(s: string): number | null {
  const norm = s.trim().replace(',', '.')
  if (!norm) return null
  const n = Number(norm)
  if (!Number.isFinite(n)) return null
  return props.integer ? Math.round(n) : n
}

function onInput(v: string) {
  const cleaned = props.integer ? v.replace(/[^0-9]/g, '') : v.replace(/[^0-9.,]/g, '')
  text.value = cleaned
  focusedValue = cleaned
  emit('update:modelValue', parse(cleaned))
}

function onBlur() {
  focusedValue = null
  text.value = format(parse(text.value))
}
</script>

<template>
  <TnInput
    :model-value="text"
    :label="label"
    :placeholder="placeholder"
    :size="size"
    :required="required"
    :disabled="disabled"
    :error="error"
    :inputmode="integer ? 'numeric' : 'decimal'"
    :aria-label="ariaLabel"
    @update:model-value="onInput"
    @blur="onBlur"
  />
</template>
