<template>
  <div ref="root" class="pmi" :class="{ pmi_compact: compact }">
    <input
      ref="input"
      class="pmi__input"
      :class="{ pmi__input_compact: compact }"
      type="text"
      autocomplete="off"
      spellcheck="false"
      role="combobox"
      :aria-expanded="open && items.length > 0"
      :aria-controls="listId"
      :aria-activedescendant="active >= 0 ? `${listId}-${active}` : undefined"
      :aria-label="ariaLabel"
      :placeholder="placeholder"
      :value="text"
      @focus="onFocus"
      @input="onInput"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.enter.prevent="onEnter"
      @keydown.escape="close"
      @keydown.tab="close"
      @blur="onBlur"
    />
    <Teleport to="body">
      <div
        v-if="open && (items.length || hint)"
        :id="listId"
        class="pmi__list tn-select__wrapper-desktop"
        role="listbox"
        :style="listStyle"
        @mousedown.prevent
      >
        <ul v-if="items.length" class="tn-select__flat-list-container">
          <li
            v-for="(o, i) in items"
            :id="`${listId}-${i}`"
            :key="`${o.category}/${o.mark}`"
            class="tn-select__flat-list-item pmi__item"
            :class="{ 'tn-select__flat-list-item_selected': i === active }"
            role="option"
            :aria-selected="i === active"
            @mouseenter="active = i"
            @click="pick(o)"
          >
            <span class="tn-select__flat-list-title pmi__mark">{{ o.mark }}</span>
            <span class="pmi__meta">{{ o.categoryLabel }} · {{ num(o.massPerMeter) }} кг/м</span>
          </li>
        </ul>
        <p v-if="hint" class="tn-select__empty-list-hint">{{ hint }}</p>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useProfileCatalogStore } from "@/stores/profileCatalog";
import { num } from "@/utils/format";
import { exactProfile, suggestProfiles, type ProfileOption } from "@/utils/profileSuggest";

/**
 * Поле ручного ввода номера профиля с подсказками из справочника масс.
 * По мере набора показывает подходящие марки («35б» → 35Б1, 35Б2 …) с видом
 * профиля и массой 1 м; выбор из списка отдаёт запись справочника (`pick`),
 * Enter или уход из поля с текстом, которого в справочнике нет, — сам текст
 * (`commit`). Список рисуется через Teleport, чтобы его не срезал прокручиваемый
 * контейнер таблицы.
 */
const props = withDefaults(
  defineProps<{
    modelValue: string;
    /** Вид профиля строки — его марки в списке первыми («140х5» есть и у круглой, и у квадратной трубы). */
    preferCategory?: string;
    placeholder?: string;
    ariaLabel?: string;
    compact?: boolean;
    limit?: number;
  }>(),
  { preferCategory: "", placeholder: "например, 35Б2", ariaLabel: "Номер профиля", compact: false, limit: 12 }
);
const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
  (e: "pick", option: ProfileOption): void;
  (e: "commit", value: string): void;
}>();

let seq = 0;
const listId = `pmi-list-${++seq}-${Math.random().toString(36).slice(2, 7)}`;
const catalog = useProfileCatalogStore();
const root = ref<HTMLElement | null>(null);
const input = ref<HTMLInputElement | null>(null);
const text = ref(props.modelValue || "");
const open = ref(false);
const active = ref(-1);
const listStyle = ref<Record<string, string>>({});
/** После выбора из списка поле теряет фокус — этот blur не должен отдавать текст как «свою» марку. */
let suppressCommit = false;

watch(
  () => props.modelValue,
  (v) => {
    text.value = v || "";
  }
);

const items = computed<ProfileOption[]>(() =>
  open.value ? suggestProfiles(catalog.options, text.value, props.preferCategory, props.limit) : []
);
const hint = computed(() => {
  if (!open.value || !text.value.trim()) return "";
  if (catalog.loading) return "Загружаю справочник…";
  if (!catalog.loaded) return "Справочник марок недоступен";
  return items.value.length ? "" : "В справочнике нет такой марки — оставьте свою, массу 1 м введите вручную";
});

function place(): void {
  const el = input.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const width = Math.max(r.width, 280);
  const left = Math.min(r.left, Math.max(8, window.innerWidth - width - 8));
  listStyle.value = {
    position: "fixed",
    top: `${r.bottom + 4}px`,
    left: `${left}px`,
    width: `${width}px`,
    zIndex: "1300",
  };
}

function onFocus(): void {
  void catalog.load();
  show();
}

function show(): void {
  if (open.value) return;
  open.value = true;
  active.value = -1;
  place();
  window.addEventListener("scroll", place, true);
  window.addEventListener("resize", place);
}

function close(): void {
  if (!open.value) return;
  open.value = false;
  active.value = -1;
  window.removeEventListener("scroll", place, true);
  window.removeEventListener("resize", place);
}

function onInput(e: Event): void {
  text.value = (e.target as HTMLInputElement).value;
  emit("update:modelValue", text.value);
  active.value = -1;
  show();
  void nextTick(place);
}

function move(delta: number): void {
  if (!items.value.length) return;
  const n = items.value.length;
  active.value = ((active.value + delta) % n + n) % n;
}

function pick(o: ProfileOption): void {
  text.value = o.mark;
  emit("update:modelValue", o.mark);
  emit("pick", o);
  close();
  suppressCommit = true;
  input.value?.blur();
  suppressCommit = false;
}

function onEnter(): void {
  if (active.value >= 0 && items.value[active.value]) {
    pick(items.value[active.value]);
    return;
  }
  const exact = exactProfile(catalog.options, text.value, props.preferCategory);
  if (exact) {
    pick(exact);
    return;
  }
  commit();
  close();
  input.value?.blur();
}

/** Свой текст: одинаков ли он с текущей маркой — решает родитель (ему видна строка). */
function commit(): void {
  emit("commit", text.value.trim());
}

function onBlur(): void {
  // клик по пункту списка гасится mousedown.prevent, поэтому blur — это уход из поля
  close();
  if (suppressCommit) return;
  commit();
}

onBeforeUnmount(close);
</script>

<style scoped>
.pmi {
  position: relative;
  display: inline-block;
  width: 100%;
}

.pmi__input {
  width: 100%;
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--border-secondary-enabled);
  border-radius: 8px;
  background: var(--background-primary-a-enabled);
  color: var(--content-primary-a-enabled);
  font: inherit;
}

.pmi__input_compact {
  height: 32px;
  width: 132px;
  padding: 0 8px;
}

.pmi__input:focus {
  outline: none;
  border-color: var(--content-accent-enabled);
}

.pmi__item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
}

.pmi__mark {
  font-weight: 500;
  white-space: nowrap;
}

.pmi__meta {
  font-size: 12px;
  color: var(--content-secondary-enabled);
  white-space: nowrap;
}
</style>
