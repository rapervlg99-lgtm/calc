<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const isRecognize = computed(() => route.path.startsWith('/recognize'))
</script>

<template>
  <main>
    <!-- Разделы — вкладками в рабочей области. Шапки с названием продукта нет:
         она дублировала заголовок раздела, а вертикаль контента начинается
         с вкладок (единый контейнер 1440 — см. styles/app.css). -->
    <nav class="app-tabs" aria-label="Разделы">
      <router-link to="/" class="app-tab" :class="{ 'app-tab_active': !isRecognize }">Калькулятор</router-link>
      <router-link to="/recognize" class="app-tab" :class="{ 'app-tab_active': isRecognize }">Распознавание таблиц ИД</router-link>
    </nav>
    <router-view />
  </main>
</template>
