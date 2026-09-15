<script setup lang="ts">
/** Карточка TN Life: белый блок с 2px рамкой цвета собственного фона, без тени. */
withDefaults(defineProps<{ padding?: 0 | 8 | 12 | 16 | 24 | 32; radius?: 8 | 12 | 16; secondary?: boolean }>(), {
  padding: 24,
  radius: 16
})
</script>

<template>
  <div class="tn-card" :class="[`tn-card_p${padding}`, `tn-card_br${radius}`, secondary && 'tn-card_secondary']">
    <slot />
  </div>
</template>
