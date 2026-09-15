<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const isRecognize = computed(() => route.path.startsWith('/recognize'))
</script>

<template>
  <header class="app-header">
    <div class="app-header-inner">
      <router-link to="/" class="app-brand" aria-label="Калькулятор огнезащиты ТЕХНОНИКОЛЬ">
        <span class="app-brand-mark">TN</span>
        <span class="app-brand-text">
          <span class="app-brand-company">ТЕХНОНИКОЛЬ</span>
          <span class="app-brand-product">Калькулятор огнезащиты</span>
        </span>
      </router-link>
      <nav class="app-nav" aria-label="Разделы">
        <router-link to="/" class="app-nav-link" :class="{ 'app-nav-link_active': !isRecognize }">Калькулятор</router-link>
        <router-link to="/recognize" class="app-nav-link" :class="{ 'app-nav-link_active': isRecognize }">Распознавание таблиц ИД</router-link>
      </nav>
    </div>
  </header>
  <main>
    <router-view />
  </main>
</template>
