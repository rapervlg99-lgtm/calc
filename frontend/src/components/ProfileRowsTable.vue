<template>
  <div class="prt">
    <div class="prt__groups">
      <div class="prt__groups-head">
        <span class="prt__groups-title">Группа элементов</span>
        <div class="prt__groups-actions">
          <button
            type="button"
            class="btn-primary btn-sm"
            :disabled="!canAutoGroup"
            :title="canAutoGroup
              ? 'Разложить позиции по группам с названиями из колонки «Элемент конструкции»'
              : 'Ни у одной позиции не распознан элемент конструкции'"
            @click="autoGroup"
          >
            Автоматическая группировка
          </button>
          <button type="button" class="btn-ghost btn-sm" @click="addGroup">Создать группу</button>
        </div>
      </div>
      <p class="prt__groups-hint">
        «Автоматическая группировка» раскладывает позиции по группам по колонке
        «Элемент конструкции» («Балки», «Фермы», «Колонны/Стойки»…); позиции без
        элемента остаются в общем перечне. Или перетащи строку в окно группы —
        позиция уйдёт из общего списка и появится внутри группы; предел ОС и тип
        конструкции назначатся всем элементам группы.
      </p>
      <p v-if="autoNote" class="prt__groups-note" role="status">{{ autoNote }}</p>
      <div v-if="groups.length === 0" class="prt__groups-empty">
        Пока нет групп — создай и затяни в неё элементы.
      </div>
      <div v-else class="prt__groups-list">
        <div
          v-for="win in groupWindows"
          :key="win.group.id"
          class="prt__window"
          :class="{ prt__window_over: dragOverId === win.group.id }"
          @dragover.prevent="onGroupDragOver(win.group.id)"
          @dragleave="onGroupDragLeave(win.group.id)"
          @drop.prevent="onDropToGroup(win.group.id)"
        >
          <div class="prt__window-head">
            <input
              v-model="win.group.name"
              class="prt__group-name"
              aria-label="Название группы"
            />
            <select
              v-model="win.group.fireLimit"
              class="prt__group-input prt__group-select"
              aria-label="Предел ОС группы"
              @change="applyGroupAttrs(win.group.id)"
            >
              <option value="">R…</option>
              <option
                v-for="r in fireLimitChoices(win.group.fireLimit)"
                :key="r"
                :value="r"
              >
                {{ r }}
              </option>
            </select>
            <select
              v-model="win.group.bearingType"
              class="prt__group-input prt__group-select prt__bearing-select"
              aria-label="Тип конструкции группы"
              @change="applyGroupAttrs(win.group.id)"
            >
              <option value="">Тип…</option>
              <option
                v-for="t in bearingTypeChoices(win.group.bearingType)"
                :key="t"
                :value="t"
              >
                {{ t }}
              </option>
            </select>
            <span class="prt__group-count">{{ win.rows.length }} эл.</span>
            <button type="button" class="btn-ghost btn-sm" aria-label="Удалить группу" @click="removeGroup(win.group.id)">Удал.</button>
          </div>

          <div v-if="win.rows.length === 0" class="prt__window-empty">
            Перетащи сюда позиции из общего списка
          </div>
          <div v-else class="prt__window-scroll">
            <table class="prt__table">
              <thead>
                <tr>
                  <th class="prt__check" aria-label="Выбор"></th>
                  <th class="prt__idx">№</th>
                  <th>Наименование</th>
                  <th>Наименование профиля</th>
                  <th>Элемент конструкции</th>
                  <th>ГОСТ профиля</th>
                  <th class="prt__num">Уд. масса, кг/м</th>
                  <th class="prt__num">Длина, м</th>
                  <th>Статус</th>
                  <th>Обогрев</th>
                  <th>Предел ОС</th>
                  <th>Тип конструкции</th>
                  <th>Покрытие</th>
                  <th aria-label="Действия"></th>
                </tr>
              </thead>
              <tbody>
                <ProfileDataRow
                  v-for="(row, i) in win.rows"
                  :key="row.id"
                  :row="row"
                  :index="rowNo(row.id)"
                  :selected="selectedIds.has(row.id)"
                  :length-value="lengthDraft[row.id] ?? formatLength(row.lengthM)"
                  @dragstart="onRowDragStart"
                  @toggle-select="toggleSelect"
                  @length-input="onLengthInput"
                  @length-commit="commitLength"
                  @heating="onHeatingChange"
                  @fire-limit="onFireLimitChange"
                  @bearing="onBearingTypeChange"
                  @coating="onCoatingTypeChange"
                  @pick-mark="onPickMark"
                  @edit="$emit('edit', $event)"
                  @copy="$emit('copy', $event)"
                  @remove="$emit('remove', $event)"
                />
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div v-if="selectedIds.size > 0" class="prt__bulk">
        <span>Выбрано: {{ selectedIds.size }}</span>
        <select
          v-model="bulkGroupId"
          class="prt__bulk-select"
          aria-label="Группа для выбранных"
        >
          <option value="">В группу…</option>
          <option v-for="g in groups" :key="g.id" :value="g.id">
            {{ g.name }}
          </option>
        </select>
        <button type="button" class="btn-primary btn-sm" :disabled="!bulkGroupId" @click="moveSelectedToGroup">Затянуть</button>
        <button type="button" class="btn-ghost btn-sm" @click="copySelected">Копировать</button>
        <button type="button" class="btn-ghost btn-sm" @click="removeSelected">Удалить</button>
      </div>
    </div>

    <div v-if="rows.length === 0" class="prt__empty-block">
      <div class="prt__list-head">
        <div class="prt__list-title">Общий перечень</div>
        <button type="button" class="btn-primary btn-sm" @click="$emit('add')">
          + Добавить элемент
        </button>
      </div>
      <div class="prt__empty">{{ emptyText }}</div>
    </div>

    <template v-else>
      <div class="prt__list-head">
        <div class="prt__list-title">Общий перечень</div>
        <button type="button" class="btn-primary btn-sm" @click="$emit('add')">
          + Добавить элемент
        </button>
      </div>
      <div v-if="ungroupedRows.length === 0" class="prt__empty">
        Все позиции сейчас в группах.
      </div>
      <div v-else class="prt__scroll">
        <table class="prt__table">
          <thead>
            <tr>
              <th class="prt__check" aria-label="Выбор"></th>
              <th class="prt__idx">№</th>
              <th>Наименование</th>
              <th>Наименование профиля</th>
              <th>Элемент конструкции</th>
              <th>ГОСТ профиля</th>
              <th class="prt__num">Уд. масса, кг/м</th>
              <th class="prt__num">Длина, м</th>
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
            <ProfileDataRow
              v-for="(row, i) in ungroupedRows"
              :key="row.id"
              :row="row"
              :index="rowNo(row.id)"
              :selected="selectedIds.has(row.id)"
              :length-value="lengthDraft[row.id] ?? formatLength(row.lengthM)"
              @dragstart="onRowDragStart"
              @toggle-select="toggleSelect"
              @length-input="onLengthInput"
              @length-commit="commitLength"
              @heating="onHeatingChange"
              @fire-limit="onFireLimitChange"
              @bearing="onBearingTypeChange"
              @coating="onCoatingTypeChange"
              @pick-mark="onPickMark"
              @edit="$emit('edit', $event)"
              @copy="$emit('copy', $event)"
              @remove="$emit('remove', $event)"
            />
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import ProfileDataRow from "./ProfileDataRow.vue";
import { bearingTypeChoices } from "@/utils/bearingTypes";
import {
  isCoatingAvailableForFireLimit
} from "@/utils/coatingTypes";
import { fireLimitChoices } from "@/utils/fireLimits";
import { autoGroupByConstruction, hasConstructions } from "@/utils/autoGroup";
import type { OgzRow, OgzRowPatch, ProfileCandidate } from "@/types/ogz";

export interface ElementGroup {
  id: string;
  name: string;
  fireLimit: string;
  bearingType: string;
  rowIds: number[];
}

const props = defineProps<{ rows: OgzRow[]; emptyText: string }>();
const emit = defineEmits<{
  (e: "edit", row: OgzRow): void;
  (e: "add"): void;
  (e: "copy", row: OgzRow): void;
  (e: "remove", row: OgzRow): void;
  (e: "copy-many", rowIds: number[]): void;
  (e: "remove-many", rowIds: number[]): void;
  (e: "patch", rowId: number, patch: OgzRowPatch): void;
  (e: "patch-many", rowIds: number[], patch: OgzRowPatch): void;
}>();

const groups = ref<ElementGroup[]>([]);
const selectedIds = ref<Set<number>>(new Set());
const bulkGroupId = ref("");
const dragRowId = ref<number | null>(null);
const dragOverId = ref<string | null>(null);
const lengthDraft = reactive<Record<number, string>>({});
const autoNote = ref("");
let groupSeq = 1;

const canAutoGroup = computed(() => hasConstructions(props.rows));

const groupedIdSet = computed(() => {
  const ids = new Set<number>();
  for (const g of groups.value) {
    for (const id of g.rowIds) ids.add(id);
  }
  return ids;
});

const groupWindows = computed(() => {
  const byId = new Map(props.rows.map((r) => [r.id, r]));
  return groups.value.map((group) => ({
    group,
    rows: group.rowIds
      .map((id) => byId.get(id))
      .filter((r): r is OgzRow => !!r)
  }));
});

const ungroupedRows = computed(() =>
  props.rows.filter((r) => !groupedIdSet.value.has(r.id))
);

// «№» строки — порядковый номер в общем перечне погонажа, один и тот же в
// группе и в общем списке: на него ссылается предупреждение «требуют проверки
// — № 3, 6», и он не должен меняться от перетаскивания строки в группу.
const rowNumbers = computed(() => new Map(props.rows.map((r, i) => [r.id, i + 1])));
function rowNo(id: number): number {
  return rowNumbers.value.get(id) ?? 0;
}

const lastLength = new Map<number, number>();   // lengthM строки при последнем обновлении черновика
watch(
  () => props.rows,
  (rows) => {
    const ids = new Set(rows.map((r) => r.id));
    for (const g of groups.value) {
      g.rowIds = g.rowIds.filter((id) => ids.has(id));
    }
    for (const id of [...selectedIds.value]) {
      if (!ids.has(id)) selectedIds.value.delete(id);
    }
    for (const row of rows) {
      // черновик длины обновляется, когда сама длина строки изменилась
      // извне (выбор марки из вариантов, правка в редакторе) — иначе поле
      // показывало старое значение, пока пользователь его не тронет
      if (lengthDraft[row.id] === undefined || lastLength.get(row.id) !== row.lengthM) {
        lengthDraft[row.id] = formatLength(row.lengthM);
        lastLength.set(row.id, row.lengthM);
      }
    }
  },
  { immediate: true, deep: true }
);

function formatLength(v: number): string {
  return v ? String(v) : "";
}

function onHeatingChange(row: OgzRow, value: string): void {
  if (value === row.heatingSides) return;
  emit("patch", row.id, { heatingSides: value });
}

function toggleSelect(id: number): void {
  const next = new Set(selectedIds.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selectedIds.value = next;
}

function addGroup(): void {
  groups.value.push({
    id: `g-${groupSeq++}`,
    name: `Группа ${groups.value.length + 1}`,
    fireLimit: "",
    bearingType: "",
    rowIds: []
  });
}

function removeGroup(id: string): void {
  groups.value = groups.value.filter((g) => g.id !== id);
  if (bulkGroupId.value === id) bulkGroupId.value = "";
}

/**
 * «Автоматическая группировка»: строки раскладываются по группам с названиями
 * из колонки «Элемент конструкции» (Балки, Фермы, Колонны/Стойки…). Группа с
 * таким названием переиспользуется вместе с её пределом ОС и типом конструкции,
 * и они применяются к пришедшим строкам — как при ручном перетаскивании.
 */
function autoGroup(): void {
  const res = autoGroupByConstruction(props.rows, groups.value, (name) => ({
    id: `g-${groupSeq++}`,
    name,
    fireLimit: "",
    bearingType: "",
    rowIds: []
  }));
  groups.value = res.groups;
  if (bulkGroupId.value && !res.groups.some((g) => g.id === bulkGroupId.value)) {
    bulkGroupId.value = "";
  }
  for (const id of res.touched) applyGroupAttrs(id);
  const groupsWithRows = res.groups.filter((g) => g.rowIds.length > 0).length;
  const parts = [`Распределено ${res.grouped} ${plural(res.grouped, "позиция", "позиции", "позиций")} по ${groupsWithRows} ${plural(groupsWithRows, "группе", "группам", "группам")}`];
  if (res.created) parts.push(`новых групп: ${res.created}`);
  if (res.skipped) parts.push(`без элемента конструкции: ${res.skipped} — оставлены как есть`);
  autoNote.value = parts.join("; ") + ".";
}

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

function onRowDragStart(rowId: number, ev: DragEvent): void {
  dragRowId.value = rowId;
  ev.dataTransfer?.setData("text/plain", String(rowId));
  if (ev.dataTransfer) ev.dataTransfer.effectAllowed = "move";
}

function onGroupDragOver(groupId: string): void {
  dragOverId.value = groupId;
}

function onGroupDragLeave(groupId: string): void {
  if (dragOverId.value === groupId) dragOverId.value = null;
}

function onDropToGroup(groupId: string): void {
  dragOverId.value = null;
  const rowId = dragRowId.value;
  dragRowId.value = null;
  if (rowId == null) return;
  assignRowsToGroup(groupId, [rowId]);
}

function moveSelectedToGroup(): void {
  if (!bulkGroupId.value) return;
  assignRowsToGroup(bulkGroupId.value, [...selectedIds.value]);
  selectedIds.value = new Set();
  bulkGroupId.value = "";
}

function copySelected(): void {
  const ids = [...selectedIds.value];
  if (!ids.length) return;
  emit("copy-many", ids);
  selectedIds.value = new Set();
}

function removeSelected(): void {
  const ids = [...selectedIds.value];
  if (!ids.length) return;
  emit("remove-many", ids);
  selectedIds.value = new Set();
}

function assignRowsToGroup(groupId: string, rowIds: number[]): void {
  const target = groups.value.find((g) => g.id === groupId);
  if (!target) return;
  for (const g of groups.value) {
    if (g.id === groupId) continue;
    g.rowIds = g.rowIds.filter((id) => !rowIds.includes(id));
  }
  const set = new Set(target.rowIds);
  for (const id of rowIds) set.add(id);
  target.rowIds = [...set];
  applyGroupAttrs(groupId);
}

function applyGroupAttrs(groupId: string): void {
  const g = groups.value.find((x) => x.id === groupId);
  if (!g || g.rowIds.length === 0) return;
  const fireLimit = g.fireLimit.trim();
  const bearingType = g.bearingType.trim();
  if (!fireLimit && !bearingType) return;

  const rowsById = new Map(props.rows.map((r) => [r.id, r]));
  const patches = g.rowIds.map((id) => {
    const row = rowsById.get(id);
    const patch: OgzRowPatch = {};
    if (fireLimit) patch.fireLimit = fireLimit;
    if (bearingType) patch.bearingType = bearingType;
    if (
      fireLimit &&
      row?.coatingType &&
      !isCoatingAvailableForFireLimit(row.coatingType, fireLimit)
    ) {
      patch.coatingType = "";
    }
    return { id, patch };
  });

  const first = JSON.stringify(patches[0]?.patch ?? {});
  const allSame = patches.every((p) => JSON.stringify(p.patch) === first);
  if (allSame) {
    emit(
      "patch-many",
      patches.map((p) => p.id),
      patches[0].patch
    );
  } else {
    for (const p of patches) emit("patch", p.id, p.patch);
  }
}

function onFireLimitChange(row: OgzRow, value: string): void {
  if (value === row.fireLimit) return;
  const patch: OgzRowPatch = { fireLimit: value };
  if (
    row.coatingType &&
    !isCoatingAvailableForFireLimit(row.coatingType, value)
  ) {
    patch.coatingType = "";
  }
  emit("patch", row.id, patch);
}

function onBearingTypeChange(row: OgzRow, value: string): void {
  if (value === row.bearingType) return;
  emit("patch", row.id, { bearingType: value });
}

/**
 * Выбор марки из вариантов OCR («2011» → 20Ш1): подставляем марку, а если она
 * есть в справочнике — и массу 1 м (длина пересчитается из массы в patch),
 * строка уходит на проверку. Список вариантов снимается.
 */
function onPickMark(row: OgzRow, cand: ProfileCandidate): void {
  const patch: OgzRowPatch = { profileMark: cand.mark, profileCandidates: [] };
  if (cand.massPerMeter > 0) {
    patch.massPerMeter = cand.massPerMeter;
    patch.massSource = cand.source;
    patch.status = "Требует проверки";
  }
  emit("patch", row.id, patch);
}

function onCoatingTypeChange(row: OgzRow, value: string): void {
  if (value === row.coatingType) return;
  emit("patch", row.id, { coatingType: value });
}

function onLengthInput(rowId: number, value: string): void {
  lengthDraft[rowId] = value;
}

function commitLength(row: OgzRow): void {
  const raw = (lengthDraft[row.id] ?? "").trim().replace(",", ".");
  if (raw === "") {
    lengthDraft[row.id] = formatLength(row.lengthM);
    return;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) {
    lengthDraft[row.id] = formatLength(row.lengthM);
    return;
  }
  if (value === row.lengthM) return;
  emit("patch", row.id, { lengthM: value });
}

/** Snapshot for calculator prefill: named groups with member row ids. */
function getGroupsForPrefill(): { title: string; rowIds: number[] }[] {
  return groups.value
    .map((g) => ({
      title: g.name.trim() || `Группа ${g.id}`,
      rowIds: [...g.rowIds]
    }))
    .filter((g) => g.rowIds.length > 0);
}

defineExpose({ getGroupsForPrefill });
</script>

<style scoped>
.prt {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.prt__groups {
  margin: 0 16px;
  padding: 12px;
  border: 1px dashed var(--border-secondary-enabled);
  border-radius: 12px;
  background: var(--background-secondary-enabled, #f7f8fa);
}

.prt__groups-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.prt__groups-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.prt__groups-note {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--content-primary-a-enabled);
}

.prt__groups-title {
  font-weight: 600;
  color: var(--content-primary-a-enabled);
}

.prt__groups-hint,
.prt__groups-empty,
.prt__window-empty {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--content-secondary-enabled);
}

.prt__window-empty {
  margin: 0;
  padding: 16px 12px;
  text-align: center;
  border-top: 1px dashed var(--border-secondary-enabled);
}

.prt__groups-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}

.prt__window {
  border: 1px solid var(--border-secondary-enabled);
  border-radius: 12px;
  background: var(--background-primary-a-enabled);
  overflow: hidden;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.prt__window_over {
  border-color: var(--content-accent-enabled);
  box-shadow: 0 0 0 2px var(--orange-10, #fff4e5);
}

.prt__window-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--background-secondary-enabled, #f7f8fa);
  border-bottom: 1px solid var(--border-secondary-enabled);
}

.prt__window-scroll {
  overflow-x: auto;
}

.prt__group-name,
.prt__group-input,
.prt__group-select,
.prt__bulk-select {
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--border-secondary-enabled);
  border-radius: 8px;
  background: var(--background-primary-a-enabled);
  font: inherit;
}

.prt__group-name {
  min-width: 120px;
  flex: 1;
  font-weight: 600;
}

.prt__group-input {
  width: 110px;
}

.prt__group-select {
  width: 96px;
  cursor: pointer;
}

.prt__bearing-select {
  width: 140px;
}

.prt__group-count {
  font-size: 12px;
  color: var(--content-secondary-enabled);
}

.prt__bulk {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  font-size: 13px;
}

.prt__list-title {
  margin: 0;
  font-weight: 600;
  color: var(--content-primary-a-enabled);
}

.prt__list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 4px 16px 0;
}

.prt__empty-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.prt__empty {
  padding: 24px;
  color: var(--content-secondary-enabled);
  text-align: center;
}

.prt__scroll {
  overflow-x: auto;
}

.prt__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.prt__table :deep(th),
.prt__table :deep(td) {
  padding: 8px 12px;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid var(--border-secondary-enabled);
}

.prt__table th {
  font-weight: 600;
  color: var(--content-secondary-enabled);
}

.prt__num {
  text-align: right;
}

.prt__idx,
.prt__check {
  text-align: center;
  color: var(--content-secondary-enabled);
}
</style>
