<script setup lang="ts">
import type { HeatedSides } from '../../types/api'
import { APP_BASE } from '../../utils/api'

/**
 * Стороны нагрева: пиктограмма профиля из img/roll (от префикса приложения) и четыре кликабельные
 * полосы вокруг неё (красная — сторона обогревается).
 */
const props = defineProps<{ sides: HeatedSides; picture: string; caption?: string }>()
const emit = defineEmits<{ (e: 'toggle', side: keyof HeatedSides): void }>()

const BARS: { side: keyof HeatedSides; cls: string; title: string }[] = [
  { side: 'top', cls: 'calc-side-bar_t', title: 'Верх' },
  { side: 'bottom', cls: 'calc-side-bar_b', title: 'Низ' },
  { side: 'left', cls: 'calc-side-bar_l', title: 'Слева' },
  { side: 'right', cls: 'calc-side-bar_r', title: 'Справа' }
]

function count(): number {
  return (['top', 'right', 'bottom', 'left'] as (keyof HeatedSides)[]).filter((k) => props.sides[k]).length
}
</script>

<template>
  <div class="calc-sides">
    <div class="calc-sides-title">Стороны нагрева</div>
    <div class="calc-sides-box">
      <img :src="`${APP_BASE}img/roll/${picture}.svg`" :alt="picture" class="calc-sides-img" />
      <button
        v-for="b in BARS"
        :key="b.side"
        type="button"
        class="calc-side-bar"
        :class="[b.cls, sides[b.side] && 'calc-side-bar_on']"
        :title="b.title"
        :aria-pressed="sides[b.side]"
        @click="emit('toggle', b.side)"
      />
    </div>
    <div class="calc-sides-label">{{ caption ?? `${count()} из 4 сторон` }}</div>
  </div>
</template>
