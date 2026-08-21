<template>
  <div class="rows">
    <div v-if="rows.length === 0" class="rows__empty">
      {{ emptyText }}
    </div>

    <div v-else class="rows__scroll">
      <table class="rows__table">
        <thead>
          <tr>
            <th class="rows__idx">№</th>
            <th>Наименование</th>
            <th>{{ kind === "sheet" ? "Номер профиля" : "Профиль" }}</th>
            <th class="rows__num">{{ kind === "sheet" ? "Масса 1 м²" : "Масса 1 м" }}</th>
            <th class="rows__num">{{ kind === "sheet" ? "Площадь, м²" : "Длина, м" }}</th>
            <th
              title="Уверенность ИИ в распознанном содержимом и готовность строки"
            >
              Статус
            </th>
            <th>Обогрев</th>
            <th>Предел ОС</th>
            <th>Тип конструкции</th>
            <th>Покрытие</th>
            <th aria-label="Действия"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, i) in rows"
            :key="row.id"
            :class="{ 'rows__row_attention': needsAttention(row) }"
          >
            <td class="rows__idx">{{ i + 1 }}</td>
            <td>{{ row.name || "—" }}</td>
            <td>{{ row.profileMark || row.profileRaw || "—" }}</td>
            <td class="rows__num">{{ row.massPerMeter ? num(row.massPerMeter) : "—" }}</td>
            <td class="rows__num">
              {{ kind === "sheet" ? cell(row.areaM2) : cell(row.lengthM) }}
            </td>
            <td><StatusTag :status="row.status" /></td>
            <td>
              <HeatingSidesPicker
                compact
                :model-value="row.heatingSides.trim() || '4'"
                :aria-label="`Обогрев ${row.name || row.profileMark || 'строка'}`"
                @update:model-value="onHeatingChange(row, $event)"
              />
            </td>
            <td>{{ row.fireLimit || "—" }}</td>
            <td>
              <select
                class="rows__select"
                :value="row.bearingType"
                :aria-label="`Тип конструкции ${row.name || row.profileMark || 'строка'}`"
                @change="onBearingTypeChange(row, ($event.target as HTMLSelectElement).value)"
              >
                <option value="">—</option>
                <option
                  v-for="t in bearingTypeChoices(row.bearingType)"
                  :key="t"
                  :value="t"
                >
                  {{ t }}
                </option>
              </select>
            </td>
            <td>
              <select
                class="rows__select rows__coating-select"
                :value="row.coatingType"
                :aria-label="`Покрытие ${row.name || row.profileMark || 'строка'}`"
                @change="onCoatingTypeChange(row, ($event.target as HTMLSelectElement).value)"
              >
                <option value="">—</option>
                <option
                  v-for="t in coatingTypeChoices(row.coatingType, row.fireLimit)"
                  :key="t"
                  :value="t"
                >
                  {{ t }}
                </option>
              </select>
            </td>
            <td>
              <button type="button" class="btn-ghost btn-sm" aria-label="Редактировать строку" @click="$emit('edit', row)">Изм.</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import HeatingSidesPicker from "./HeatingSidesPicker.vue";
import StatusTag from "./StatusTag.vue";
import { bearingTypeChoices } from "@/utils/bearingTypes";
import { coatingTypeChoices } from "@/utils/coatingTypes";
import { num } from "@/utils/format";
import type { OgzRow, OgzRowPatch } from "@/types/ogz";

defineProps<{ kind: "profile" | "sheet"; rows: OgzRow[]; emptyText: string }>();
const emit = defineEmits<{
  (e: "edit", row: OgzRow): void;
  (e: "patch", rowId: number, patch: OgzRowPatch): void;
}>();

function cell(v: number): string {
  return v ? num(v) : "—";
}

function onHeatingChange(row: OgzRow, value: string): void {
  if (value === row.heatingSides) return;
  emit("patch", row.id, { heatingSides: value });
}

function onBearingTypeChange(row: OgzRow, value: string): void {
  if (value === row.bearingType) return;
  emit("patch", row.id, { bearingType: value });
}

function onCoatingTypeChange(row: OgzRow, value: string): void {
  if (value === row.coatingType) return;
  emit("patch", row.id, { coatingType: value });
}

function needsAttention(row: OgzRow): boolean {
  return (
    row.status === "Требует проверки" ||
    row.status === "Нужен ввод массы" ||
    row.status === "Нет данных"
  );
}
</script>

<style scoped>
.rows__empty {
  padding: 24px;
  color: var(--content-secondary-enabled);
  text-align: center;
}

.rows__scroll {
  overflow-x: auto;
}

.rows__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.rows__table th,
.rows__table td {
  padding: 8px 12px;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid var(--border-secondary-enabled);
}

.rows__table th {
  font-weight: 600;
  color: var(--content-secondary-enabled);
}

.rows__num {
  text-align: right;
}

.rows__idx {
  text-align: right;
  color: var(--content-secondary-enabled);
}

.rows__row_attention {
  background: var(--orange-10);
}

.rows__select {
  height: 32px;
  width: 140px;
  padding: 0 8px;
  border: 1px solid var(--border-secondary-enabled);
  border-radius: 8px;
  background: var(--background-primary-a-enabled);
  font: inherit;
  cursor: pointer;
}

.rows__coating-select {
  width: 220px;
  max-width: 28vw;
}
</style>
