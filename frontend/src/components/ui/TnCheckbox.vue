<script setup lang="ts">
import { useId } from 'vue'

/** Чекбокс TN Life (uikit/checkbox): красная заливка во включённом состоянии. */
withDefaults(defineProps<{ modelValue?: boolean; label?: string; description?: string; error?: string; disabled?: boolean }>(), {
  modelValue: false
})
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()
const id = useId()
</script>

<template>
  <label class="tn-checkbox" :class="{ 'tn-checkbox_has-label': !!label, 'tn-checkbox_disabled': disabled }">
    <button
      :id="id"
      type="button"
      role="checkbox"
      class="tn-checkbox__btn"
      :class="{ 'tn-checkbox__btn_checked': modelValue, 'tn-checkbox__btn_disabled': disabled }"
      :aria-checked="modelValue"
      :disabled="disabled"
      @click="emit('update:modelValue', !modelValue)"
      @mouseup="($event.currentTarget as HTMLButtonElement).blur()"
    />
    <span v-if="label" class="tn-checkbox__text">
      <label class="tn-checkbox__text-inner" :for="id">{{ label }}</label>
      <span v-if="description" class="tn-checkbox__description">{{ description }}</span>
      <span v-if="error" class="tn-checkbox__text-error">{{ error }}</span>
    </span>
  </label>
</template>
