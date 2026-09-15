<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getExtJob } from '../../utils/extApi'

const route = useRoute()
const router = useRouter()
const status = ref('pending')
const err = ref('')
let timer: ReturnType<typeof setInterval> | null = null
let stopped = false

async function tick() {
  const id = String(route.params.id || '')
  try {
    const job = await getExtJob(id)
    status.value = job.status
    if (job.status === 'ready') {
      stop()
      await router.replace(`/recognize/jobs/${id}`)
    } else if (job.status === 'failed') {
      stop()
      err.value = 'Распознавание не удалось. Попробуйте демо-форму или другой PDF.'
    }
  } catch (e: any) {
    err.value = e?.message || 'Ошибка опроса статуса'
  }
}

function stop() {
  stopped = true
  if (timer) clearInterval(timer)
  timer = null
}

onMounted(() => {
  void tick()
  timer = setInterval(() => {
    if (!stopped) void tick()
  }, 2000)
})

onUnmounted(stop)
</script>

<template>
  <div class="ozm-page recognize-page">
    <div class="ozm-top">
      <h1 class="ozm-title">Обработка</h1>
      <router-link class="btn-ghost" to="/recognize">← Назад</router-link>
    </div>
    <p class="recognize-lead">Статус задания: <strong>{{ status }}</strong></p>
    <p class="muted">Распознаём PDF… это может занять несколько минут.</p>
    <p v-if="err" class="error">{{ err }}</p>
    <div class="page-actions" style="margin-top:24px">
      <router-link class="btn-add" to="/recognize">Демо-форма</router-link>
    </div>
  </div>
</template>
