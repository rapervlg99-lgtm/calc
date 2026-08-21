<template>
  <tr
    class="pdr"
    :class="{ pdr_attention: needsAttention }"
    draggable="true"
    @dragstart="$emit('dragstart', row.id, $event)"
  >
    <td class="pdr__check">
      <input
        type="checkbox"
        :checked="selected"
        :aria-label="`Выбрать ${label}`"
        @change="$emit('toggle-select', row.id)"
      />
    </td>
    <td class="pdr__idx">{{ index }}</td>
    <td>{{ row.profileMark || row.profileRaw || row.name || "—" }}</td>
    <td>{{ constructionLabel }}</td>
    <td>{{ row.gostProfile || "—" }}</td>
    <td class="pdr__num">
      {{ row.massPerMeter ? num(row.massPerMeter) : "—" }}
    </td>
    <td class="pdr__num">
      <input
        class="pdr__length"
        type="text"
        inputmode="decimal"
        :value="lengthValue"
        :aria-label="`Длина ${label}`"
        @input="
          $emit('length-input', row.id, ($event.target as HTMLInputElement).value)
        "
        @change="$emit('length-commit', row)"
        @keydown.enter="($event.target as HTMLInputElement).blur()"
      />
    </td>
    <td>
      <StatusTag :status="row.status" />
    </td>
    <td @mousedown.stop>
      <HeatingSidesPicker
        compact
        :model-value="row.heatingSides.trim() || '4'"
        :aria-label="`Обогрев ${label}`"
        @update:model-value="$emit('heating', row, $event)"
      />
    </td>
    <td :class="{ pdr__missing: !row.fireLimit }">
      <select
        class="pdr__select"
        :value="row.fireLimit"
        :aria-label="`Предел ОС ${label}`"
        @change="
          $emit('fire-limit', row, ($event.target as HTMLSelectElement).value)
        "
      >
        <option value="">—</option>
        <option
          v-for="r in fireLimitChoices(row.fireLimit)"
          :key="r"
          :value="r"
        >
          {{ r }}
        </option>
      </select>
    </td>
    <td>
      <select
        class="pdr__select pdr__bearing"
        :value="row.bearingType"
        :aria-label="`Тип конструкции ${label}`"
        @change="
          $emit('bearing', row, ($event.target as HTMLSelectElement).value)
        "
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
        class="pdr__select pdr__coating"
        :value="row.coatingType"
        :aria-label="`Покрытие ${label}`"
        @change="
          $emit('coating', row, ($event.target as HTMLSelectElement).value)
        "
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
    <td class="pdr__actions" @mousedown.stop>
      <button type="button" class="btn-ghost btn-sm" aria-label="Редактировать строку" @click="$emit('edit', row)">Изм.</button>
      <button type="button" class="btn-ghost btn-sm" aria-label="Копировать строку" @click="$emit('copy', row)">Копир.</button>
      <button type="button" class="btn-ghost btn-sm pdr__del" aria-label="Удалить строку" @click="$emit('remove', row)">Удал.</button>
    </td>
  </tr>
</template>

<script setup lang="ts">
import { computed } from "vue";
import HeatingSidesPicker from "./HeatingSidesPicker.vue";
import StatusTag from "./StatusTag.vue";
import { bearingTypeChoices } from "@/utils/bearingTypes";
import { coatingTypeChoices } from "@/utils/coatingTypes";
import { constructionLabel as formatConstruction } from "@/utils/constructionLabel";
import { fireLimitChoices } from "@/utils/fireLimits";
import { num } from "@/utils/format";
import type { OgzRow } from "@/types/ogz";

const props = defineProps<{
  row: OgzRow;
  index: number;
  selected: boolean;
  lengthValue: string;
}>();

defineEmits<{
  (e: "dragstart", rowId: number, event: DragEvent): void;
  (e: "toggle-select", rowId: number): void;
  (e: "length-input", rowId: number, value: string): void;
  (e: "length-commit", row: OgzRow): void;
  (e: "heating", row: OgzRow, value: string): void;
  (e: "fire-limit", row: OgzRow, value: string): void;
  (e: "bearing", row: OgzRow, value: string): void;
  (e: "coating", row: OgzRow, value: string): void;
  (e: "edit", row: OgzRow): void;
  (e: "copy", row: OgzRow): void;
  (e: "remove", row: OgzRow): void;
}>();

const label = computed(() =>
  `${props.row.profileMark || props.row.profileRaw || "профиль"} ${props.row.construction || ""}`.trim()
);

const constructionLabel = computed(() => {
  const formatted = formatConstruction(props.row.construction);
  return formatted || "—";
});

const needsAttention = computed(
  () =>
    props.row.status === "Требует проверки" ||
    props.row.status === "Нужен ввод массы" ||
    props.row.status === "Нет данных" ||
    !props.row.fireLimit
);
</script>

<style scoped>
.pdr {
  cursor: grab;
}

.pdr:active {
  cursor: grabbing;
}

.pdr_attention {
  background: var(--orange-10);
}

.pdr__num {
  text-align: right;
}

.pdr__idx,
.pdr__check {
  text-align: center;
  color: var(--content-secondary-enabled);
}

.pdr__length,
.pdr__select {
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--border-secondary-enabled);
  border-radius: 8px;
  background: var(--background-primary-a-enabled);
  font: inherit;
}

.pdr__length {
  width: 88px;
  text-align: right;
}

.pdr__select {
  width: 96px;
  cursor: pointer;
}

.pdr__bearing {
  width: 140px;
}

.pdr__coating {
  width: 220px;
  max-width: 28vw;
}

.pdr__missing {
  color: var(--content-system-negative);
}

.pdr__actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 4px;
}

.pdr__del:hover {
  color: var(--content-system-negative, #c62828);
}
</style>
