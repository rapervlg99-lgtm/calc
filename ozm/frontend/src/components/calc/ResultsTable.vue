<script setup lang="ts">
import { ref } from 'vue'
import TnIcon from '../ui/TnIcon.vue'
import type { ElementResult } from '../../types/api'
import { fmt, liningLabel, resultOutput, resultDelta } from '../../utils/calcView'

/** Таблица результатов по элементам с раскрывающимся трейсом расчёта. */
const props = defineProps<{
  rows: ElementResult[]
  coatLabel: (coat: string) => string
  shapeLabel: (shape: string) => string
  traceFor: (id: string) => string[]
}>()

const open = ref<string | null>(null)
function toggle(id: string) {
  open.value = open.value === id ? null : id
}
function deltaColor(r: ElementResult): string {
  return r.exclusion ? (r.coat === '1.5' ? 'var(--content-system-warning)' : 'var(--content-system-negative)') : 'var(--content-primary-a-enabled)'
}
</script>

<template>
  <div class="calc-results-scroll">
    <div class="calc-results">
      <div class="calc-res-grid calc-res-head">
        <div />
        <div>Элемент</div>
        <div>Профиль</div>
        <div>R</div>
        <div>Покрытие</div>
        <div>Метод</div>
        <div class="calc-num">δпр, мм</div>
        <div class="calc-num">δ, мм</div>
        <div class="calc-num">S, м²</div>
        <div class="calc-num">Объём / масса</div>
      </div>
      <div v-for="r in props.rows" :key="r.id" class="calc-res-item">
        <div class="calc-res-grid calc-res-row" :class="{ 'calc-res-row_open': open === r.id }" @click="toggle(r.id)">
          <div class="calc-res-chevron" :class="{ 'calc-res-chevron_open': open === r.id }"><TnIcon name="down-s" :size="20" /></div>
          <div class="calc-ellipsis" style="font-weight: 600" :title="r.title">{{ r.title }}</div>
          <div class="calc-ellipsis" style="color: var(--content-secondary-enabled)">{{ shapeLabel(r.shape) }}</div>
          <div>R{{ r.htLevel }}</div>
          <div class="calc-ellipsis" style="color: var(--content-secondary-enabled)">{{ coatLabel(r.coat) }}</div>
          <div style="color: var(--content-secondary-enabled)">{{ liningLabel(r.lining) }}</div>
          <div class="calc-num">{{ fmt(r.dpr, 2) }}</div>
          <div class="calc-num" style="font-weight: 600" :style="{ color: deltaColor(r) }">{{ resultDelta(r) }}</div>
          <div class="calc-num">{{ fmt(r.areaM2, 1) }}</div>
          <div class="calc-num">{{ resultOutput(r) }}</div>
        </div>
        <div v-if="open === r.id" class="calc-res-detail">
          <div v-if="r.exclusion" class="calc-note" :class="r.coat === '1.5' ? 'calc-note_warn' : 'calc-note_error'">
            <TnIcon name="info" :size="20" />
            <span>{{ r.exclusion }}</span>
          </div>
          <div class="calc-trace">
            <div>F = {{ fmt(r.f, 0) }} мм² · Π = {{ fmt(r.pi, 0) }} мм · δпр = F / Π = {{ fmt(r.dpr, 2) }} мм</div>
            <div>Длина {{ fmt(r.lengthM, 2) }} м × {{ fmt(r.quantity, 0) }} шт → S = {{ fmt(r.areaM2, 3) }} м²</div>
            <div v-for="(line, i) in traceFor(r.id)" :key="i">{{ line }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
