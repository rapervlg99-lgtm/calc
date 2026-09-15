<script setup lang="ts">
/**
 * Иконка из спрайта TN Life (подмножество глифов встроено в index.html как
 * <svg id="tn-life-icon-sprite">). Монохромная, наследует currentColor.
 */
withDefaults(defineProps<{ name: string; size?: number | string; color?: string }>(), { size: 24 })
</script>

<template>
  <i
    class="tn-icon"
    :style="{ width: `${size}px`, height: `${size}px`, lineHeight: `${size}px`, color, flex: '0 0 auto' }"
  >
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" fill="none" aria-hidden="true">
      <use :href="`#icon--${name}`" :width="size" :height="size" />
    </svg>
  </i>
</template>
