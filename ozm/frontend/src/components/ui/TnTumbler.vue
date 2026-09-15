<script setup lang="ts">
/** Переключатель TN Life (uikit/tumbler). */
withDefaults(defineProps<{ modelValue?: boolean; label?: string; description?: string; block?: boolean; leftLabel?: boolean; disabled?: boolean }>(), {
  modelValue: false
})
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()
</script>

<template>
  <div class="tn-tumbler" :class="{ 'tn-tumbler_block': block, 'tn-tumbler_disabled': disabled }">
    <div v-if="leftLabel && (label || description)" class="tn-tumbler__text">
      <p v-if="label" class="tn-tumbler__text-inner">{{ label }}</p>
      <p v-if="description" class="tn-tumbler__text-description">{{ description }}</p>
    </div>
    <button
      type="button"
      role="switch"
      class="tn-tumbler__btn tn-tumbler__btn_medium"
      :class="{ 'tn-tumbler__btn_active': modelValue, 'tn-tumbler__btn_disabled': disabled }"
      :aria-checked="modelValue"
      :aria-label="label"
      :disabled="disabled"
      @click="emit('update:modelValue', !modelValue)"
    />
    <div v-if="!leftLabel && (label || description)" class="tn-tumbler__text">
      <p v-if="label" class="tn-tumbler__text-inner">{{ label }}</p>
      <p v-if="description" class="tn-tumbler__text-description">{{ description }}</p>
    </div>
  </div>
</template>
