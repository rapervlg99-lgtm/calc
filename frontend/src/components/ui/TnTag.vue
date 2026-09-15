<script setup lang="ts">
import TnIcon from './TnIcon.vue'

/** Тег TN Life (uikit/tag): обводка, 14/20, опциональная иконка слева. */
defineProps<{ icon?: string; inline?: boolean }>()
</script>

<template>
  <div class="tn-tag" :class="{ 'tn-tag_inline': inline, 'tn-tag_icon': !!icon }">
    <TnIcon v-if="icon" :name="icon" :size="20" class="tn-tag__icon" color="var(--content-secondary-enabled)" />
    <span class="tn-tag__text"><slot /></span>
  </div>
</template>
