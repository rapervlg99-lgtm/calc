<template>
  <div class="hsp" :class="{ hsp_compact: compact, hsp_open: open }">
    <button
      ref="triggerEl"
      type="button"
      class="hsp__trigger"
      :aria-expanded="open"
      :aria-label="ariaLabel"
      @click.stop="toggleOpen"
      @mousedown.stop
    >
      <span class="hsp__trigger-text">{{ caption }}</span>
      <span class="hsp__chevron" aria-hidden="true" />
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="menuEl"
        class="hsp__menu"
        :style="menuStyle"
        role="listbox"
        aria-multiselectable="true"
        @mousedown.stop
      >
        <label
          v-for="opt in OPTIONS"
          :key="opt.side"
          class="hsp__option"
        >
          <input
            type="checkbox"
            class="hsp__checkbox"
            :checked="sides[opt.side]"
            @change="toggle(opt.side)"
          />
          <span>{{ opt.label }}</span>
        </label>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from "vue";

type Side = "top" | "bottom" | "left" | "right";

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    compact?: boolean;
    ariaLabel?: string;
  }>(),
  {
    modelValue: "",
    compact: false,
    ariaLabel: "Стороны обогрева"
  }
);
const emit = defineEmits<{ (e: "update:modelValue", value: string): void }>();

const open = ref(false);
const triggerEl = ref<HTMLButtonElement | null>(null);
const menuEl = ref<HTMLElement | null>(null);
const menuStyle = ref<Record<string, string>>({});
const sides = reactive<Record<Side, boolean>>({
  top: false,
  bottom: false,
  left: false,
  right: false
});

/** Порядок в UI и в сохранённой строке: снизу → сверху → слева → справа. */
const OPTIONS: { side: Side; label: string }[] = [
  { side: "bottom", label: "снизу" },
  { side: "top", label: "сверху" },
  { side: "left", label: "слева" },
  { side: "right", label: "справа" }
];

const ORDER = OPTIONS.map((o) => o.side);
const LABELS: Record<Side, string> = Object.fromEntries(
  OPTIONS.map((o) => [o.side, o.label])
) as Record<Side, string>;

// Обратная совместимость: раньше «стороны обогрева» могли хранить просто число
// сторон. Разворачиваем число в каноническую раскладку для двутавра.
const CANONICAL: Record<number, Side[]> = {
  1: ["bottom"],
  2: ["left", "right"],
  3: ["bottom", "left", "right"],
  4: ["top", "bottom", "left", "right"]
};

function parse(value: string): Record<Side, boolean> {
  const result: Record<Side, boolean> = {
    top: false,
    bottom: false,
    left: false,
    right: false
  };
  const trimmed = value.trim();
  const n = Number(trimmed);
  if (trimmed !== "" && Number.isInteger(n) && CANONICAL[n]) {
    for (const s of CANONICAL[n]) result[s] = true;
    return result;
  }
  const v = trimmed.toLowerCase();
  for (const s of ORDER) {
    if (v.includes(LABELS[s])) result[s] = true;
  }
  return result;
}

// Формат лосслесс и идемпотентный: разбор собственного вывода даёт то же
// состояние, поэтому реакция на свой же update безвредна (guard не нужен).
watch(
  () => props.modelValue,
  (val) => {
    const parsed = parse(val ?? "");
    for (const s of ORDER) sides[s] = parsed[s];
  },
  { immediate: true }
);

function buildValue(): string {
  return ORDER.filter((s) => sides[s])
    .map((s) => LABELS[s])
    .join(", ");
}

function toggle(side: Side): void {
  sides[side] = !sides[side];
  emit("update:modelValue", buildValue());
}

function placeMenu(): void {
  const el = triggerEl.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  const width = Math.max(rect.width, 160);
  menuStyle.value = {
    position: "fixed",
    top: `${rect.bottom + 4}px`,
    left: `${rect.left}px`,
    width: `${width}px`,
    zIndex: "1000"
  };
}

function onDocPointerDown(e: PointerEvent): void {
  const t = e.target as Node | null;
  if (!t) return;
  if (triggerEl.value?.contains(t)) return;
  if (menuEl.value?.contains(t)) return;
  close();
}

function bindOutside(): void {
  document.addEventListener("pointerdown", onDocPointerDown, true);
}

function unbindOutside(): void {
  document.removeEventListener("pointerdown", onDocPointerDown, true);
}

async function toggleOpen(): Promise<void> {
  open.value = !open.value;
  if (open.value) {
    await nextTick();
    placeMenu();
    bindOutside();
  } else {
    unbindOutside();
  }
}

function close(): void {
  if (!open.value) return;
  open.value = false;
  unbindOutside();
}

onBeforeUnmount(unbindOutside);

const count = computed(() => ORDER.filter((s) => sides[s]).length);
const caption = computed(() => {
  const c = count.value;
  if (c === 0) return props.compact ? "—" : "Не выбрано";
  if (c === 4) return "4 стороны";
  return ORDER.filter((s) => sides[s])
    .map((s) => LABELS[s])
    .join(", ");
});
</script>

<style scoped>
.hsp {
  position: relative;
  display: inline-flex;
  flex-direction: column;
  align-items: stretch;
  min-width: 160px;
}

.hsp_compact {
  min-width: 132px;
  max-width: 200px;
}

.hsp__trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  height: 40px;
  padding: 0 10px;
  border: 1px solid var(--border-secondary-enabled);
  border-radius: 8px;
  background: var(--background-primary-a-enabled);
  font: inherit;
  color: var(--content-primary-a-enabled);
  text-align: left;
  cursor: pointer;
}

.hsp_compact .hsp__trigger {
  height: 32px;
  padding: 0 8px;
  font-size: 14px;
}

.hsp__trigger:hover,
.hsp_open .hsp__trigger {
  border-color: var(--content-accent-enabled);
}

.hsp__trigger-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hsp__chevron {
  flex-shrink: 0;
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid var(--content-secondary-enabled);
  transition: transform 0.15s ease;
}

.hsp_open .hsp__chevron {
  transform: rotate(180deg);
}

.hsp__menu {
  padding: 6px;
  border: 1px solid var(--border-secondary-enabled);
  border-radius: 10px;
  background: var(--background-primary-a-enabled);
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.12);
}

.hsp__option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 14px;
  color: var(--content-primary-a-enabled);
  cursor: pointer;
  user-select: none;
}

.hsp__option:hover {
  background: var(--background-secondary-enabled, #f7f8fa);
}

.hsp__checkbox {
  width: 16px;
  height: 16px;
  margin: 0;
  accent-color: var(--content-accent-enabled);
  cursor: pointer;
}
</style>
