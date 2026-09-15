<script setup lang="ts">
import { computed, useId } from 'vue'
import TnIcon from './TnIcon.vue'

export interface TnSelectOption { value: string; label: string }
export interface TnSelectGroup { label: string; options: TnSelectOption[] }

/**
 * Выпадающий список TN Life (uikit/select) поверх нативного <select>:
 * тот же внешний вид поля, стрелка из спрайта, нативное меню браузера.
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
  }>(),
  { modelValue: '', options: () => [], size: 's' }
)
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const id = useId()
const value = computed(() => (props.modelValue === null || props.modelValue === undefined ? '' : String(props.modelValue)))
const hasValue = computed(() => value.value !== '')
</script>

<template>
  <div class="tn-select" :class="{ 'tn-select_required': required }">
    <label v-if="label" :for="id" class="tn-select__label">{{ label }}</label>
    <p v-if="description" class="tn-select__description">{{ description }}</p>
    <div style="position: relative">
      <select
        :id="id"
        class="tn-select__inner-input tn-select__native"
        :class="[
          size === 'm' && 'tn-select__inner-input_medium',
          disabled && 'tn-select__inner-input_disabled',
          error && 'tn-select__inner-input_error',
          !hasValue && 'tn-select__native_placeholder'
        ]"
        :value="value"
        :disabled="disabled"
        :aria-label="ariaLabel"
        @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
        <template v-if="groups && groups.length">
          <optgroup v-for="g in groups" :key="g.label" :label="g.label">
            <option v-for="o in g.options" :key="o.value" :value="o.value">{{ o.label }}</option>
          </optgroup>
        </template>
        <option v-for="o in options" v-else :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <span class="tn-select__inner-arrow tn-select__arrow-static"><TnIcon name="down-s" :size="20" /></span>
    </div>
    <p v-if="error" class="tn-select__message tn-select__message_error">{{ error }}</p>
  </div>
</template>
