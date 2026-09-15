<script setup lang="ts">
import type { MaterialLine } from '../../types/api'
import { fmt } from '../../utils/calcView'

/** Ведомость материалов в разметке таблицы TN Life (без цен — решение владельца, v1). */
defineProps<{ rows: MaterialLine[] }>()

function digits(m: MaterialLine): number {
  if (m.unit === 'шт') return 0
  if (m.unit === 'м³') return 3
  return 1
}
</script>

<template>
  <div class="tn-table calc-bom">
    <div class="tn-table__header-container">
      <div class="tn-table__header-row">
        <div class="tn-table__header-cell" style="flex: 1 0 0"><div class="tn-table__header-cell-top"><span class="tn-table__header-title">Материал</span></div></div>
        <div class="tn-table__header-cell" style="flex: 0 0 120px"><div class="tn-table__header-cell-top"><span class="tn-table__header-title">Ед. изм.</span></div></div>
        <div class="tn-table__header-cell" style="flex: 0 0 160px"><div class="tn-table__header-cell-top"><span class="tn-table__header-title">Количество</span></div></div>
      </div>
    </div>
    <div class="tn-table__body-container">
      <div v-if="!rows.length" class="tn-table__empty-container calc-hint">Материалы появятся после расчёта</div>
      <div v-for="m in rows" :key="m.id" class="tn-table__body-row">
        <div class="tn-table__body-cell" style="flex: 1 0 0"><span class="tn-table__body-text">{{ m.title }}</span></div>
        <div class="tn-table__body-cell" style="flex: 0 0 120px"><span class="tn-table__body-text">{{ m.unit }}</span></div>
        <div class="tn-table__body-cell calc-num" style="flex: 0 0 160px"><span class="tn-table__body-text" style="font-variant-numeric: tabular-nums">{{ fmt(m.quantity, digits(m)) }}</span></div>
      </div>
    </div>
    <div v-if="rows.length" class="calc-bom-count" style="padding: 12px 24px 0">Позиций: {{ rows.length }}</div>
  </div>
</template>
