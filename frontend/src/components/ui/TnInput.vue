<script setup lang="ts">
import { computed, useId } from 'vue'

/** Текстовое поле TN Life (uikit/input). Значение всегда строка. */
const props = withDefaults(
  defineProps<{
    modelValue?: string | number | null
    label?: string
    description?: string
    placeholder?: string
    size?: 's' | 'm'
    required?: boolean
    disabled?: boolean
    error?: string
    inputmode?: 'text' | 'decimal' | 'numeric'
    ariaLabel?: string
  }>(),
  { modelValue: '', size: 's', placeholder: ' ', inputmode: 'text' }
)
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'blur'): void }>()

const id = useId()
const value = computed(() => (props.modelValue === null || props.modelValue === undefined ? '' : String(props.modelValue)))
</script>

<template>
  <div class="tn-input" :class="{ 'tn-input_required': required, 'tn-input_error': !!error }">
    <label v-if="label" :for="id" class="tn-input__label">{{ label }}</label>
    <p v-if="description" class="tn-input__description">{{ description }}</p>
    <div class="tn-input__inner">
      <input
        :id="id"
        class="tn-input__inner-input"
        :class="[`tn-input__inner-input_size-${size}`, error && 'tn-input__inner-input_error']"
        type="text"
        :value="value"
        :placeholder="placeholder"
        :disabled="disabled"
        :inputmode="inputmode"
        :aria-label="ariaLabel"
        autocomplete="off"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        @blur="emit('blur')"
      />
    </div>
    <p v-if="error" class="tn-input__message tn-input__message_error">{{ error }}</p>
  </div>
</template>
