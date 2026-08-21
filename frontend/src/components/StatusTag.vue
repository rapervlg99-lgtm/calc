<template>
  <span
    class="status-tag"
    :class="modifier"
    :title="hint"
  >{{ status }}</span>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { RowStatus } from "@/types/ogz";

const props = defineProps<{ status: RowStatus }>();

const hint = computed(() => {
  switch (props.status) {
    case "Требует проверки":
      return "ИИ не уверен в распознанном содержимом — проверь строку";
    case "Нужен ввод массы":
      return "Нужно вручную указать удельную массу";
    case "Нет данных":
      return "Нет данных для расчёта погонажа";
    case "Не считается":
      return "Конструкция не учитывается в расчёте ОГЗ";
    case "Посчитано":
      return "Строка рассчитана";
    default:
      return "";
  }
});

const modifier = computed(() => {
  switch (props.status) {
    case "Посчитано":
      return "status-tag_ok";
    case "Не считается":
      return "status-tag_muted";
    case "Требует проверки":
      return "status-tag_warn";
    case "Нужен ввод массы":
      return "status-tag_negative";
    case "Нет данных":
      return "status-tag_negative";
    default:
      return "status-tag_muted";
  }
});
</script>

<style scoped>
.status-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 18px;
  white-space: nowrap;
}

/* Светлые подложки берём из палитры — семантических background-токенов
   статусов в UIKit нет (design-interfaces §2: палитра как фолбэк). */
.status-tag_ok {
  color: var(--content-system-positive);
  background: var(--green-10);
}

.status-tag_warn {
  color: var(--content-system-warning);
  background: var(--orange-10);
}

.status-tag_negative {
  color: var(--content-system-negative);
  background: var(--red-10);
}

.status-tag_muted {
  color: var(--content-secondary-enabled);
  background: var(--background-secondary-enabled);
}
</style>
