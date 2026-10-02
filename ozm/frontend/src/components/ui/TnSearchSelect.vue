<script setup lang="ts">
import TnSelect from './TnSelect.vue'
import type { TnSelectOption } from './TnSelect.vue'

/**
 * Выпадающий список с поиском («Сортамент ГОСТ»): тот же TnSelect, но строка
 * поиска показывается всегда, независимо от длины списка.
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
</script>

<template>
  <TnSelect
    :model-value="props.modelValue"
    :options="props.options"
    :label="props.label"
    :placeholder="props.placeholder"
    :search-placeholder="props.searchPlaceholder"
    :size="props.size"
    :required="props.required"
    :disabled="props.disabled"
    :error="props.error"
    :empty-hint="props.emptyHint"
    searchable
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>
