<script setup lang="ts">
import { computed, useSlots } from 'vue'
import TnIcon from './TnIcon.vue'

/** Кнопка TN Life (uikit/button). Варианты: action (по умолчанию), secondary, outline, link. */
const props = withDefaults(
  defineProps<{
    size?: 'sm' | 'md' | 'lg'
    secondary?: boolean
    outline?: boolean
    link?: boolean
    disabled?: boolean
    loading?: boolean
    block?: boolean
    icon?: string
    iconRight?: string
    type?: 'button' | 'submit'
    title?: string
  }>(),
  { size: 'sm', type: 'button' }
)

const slots = useSlots()
const hasContent = computed(() => !!slots.default)
const onlyIcon = computed(() => !hasContent.value && !!props.icon)
const iconSize = computed(() => (props.size === 'lg' ? 24 : 20))

const SIZE_CLASS = { sm: 'tn-button_small', md: 'tn-button_medium', lg: 'tn-button_large' } as const

const cls = computed(() => {
  const isAction = !props.secondary && !props.link && !props.outline
  return [
    'tn-button',
    SIZE_CLASS[props.size],
    'tn-button_not-rounded',
    isAction && 'tn-button_action',
    props.secondary && !props.link && 'tn-button_default',
    props.outline && 'tn-button_outline',
    props.link && 'tn-button_link',
    props.disabled && 'tn-button_disabled',
    props.block && 'tn-button_wide',
    onlyIcon.value && 'tn-button_only-icon',
    props.loading && 'tn-button_loading'
  ].filter(Boolean)
})
</script>

<template>
  <button
    :class="cls"
    :type="type"
    :disabled="disabled"
    :title="title"
    @mouseup="($event.currentTarget as HTMLButtonElement).blur()"
  >
    <span v-if="icon" class="tn-button__icon" :class="{ 'tn-button__icon_left': !onlyIcon }">
      <TnIcon :name="icon" :size="iconSize" />
    </span>
    <span v-if="hasContent" class="tn-button__text"><slot /></span>
    <span v-if="iconRight" class="tn-button__icon tn-button__icon_right">
      <TnIcon :name="iconRight" :size="iconSize" />
    </span>
    <span v-if="loading" class="tn-button__loader">
      <TnIcon name="load" :size="iconSize" class="tn-button__loader-icon" />
    </span>
  </button>
</template>
