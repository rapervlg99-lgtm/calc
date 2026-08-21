<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { createExtJob, DEMO_JOB_ID } from '../../utils/extApi'
import { useJobStore } from '../../stores/job'

const router = useRouter()
const jobStore = useJobStore()
const busy = ref(false)
const err = ref('')
const dragOver = ref(false)

async function openDemo() {
  jobStore.openDemo()
  await router.push(`/recognize/jobs/${DEMO_JOB_ID}`)
}

async function onFile(file: File | undefined | null) {
  if (!file) return
  err.value = ''
  busy.value = true
  try {
    const { id } = await createExtJob(file)
    await router.push(`/recognize/jobs/${id}/processing`)
  } catch (e: any) {
    err.value = e?.response?.data?.error || e?.message || 'Ошибка загрузки PDF'
  } finally {
    busy.value = false
  }
}

function onInput(e: Event) {
  const input = e.target as HTMLInputElement
  void onFile(input.files?.[0])
  input.value = ''
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  void onFile(e.dataTransfer?.files?.[0])
}
</script>

<template>
  <div class="ozm-page recognize-page">
    <div class="ozm-top">
      <h1 class="ozm-title">Распознать таблицу ИД</h1>
      <router-link class="btn-ghost" to="/">← К калькулятору</router-link>
    </div>

    <p class="recognize-lead">
      Загрузите PDF со спецификацией металлоконструкций — или откройте демо-форму без OCR.
    </p>

    <div
      class="dropzone"
      :class="{ over: dragOver, busy }"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
    >
      <p class="dropzone-title">{{ busy ? 'Загрузка…' : 'Перетащите PDF сюда' }}</p>
      <p class="muted">или выберите файл</p>
      <label class="btn-primary file-btn">
        Выбрать PDF
        <input type="file" accept="application/pdf,.pdf" :disabled="busy" @change="onInput" />
      </label>
    </div>

    <div class="page-actions" style="margin-top:24px">
      <button class="btn-add" type="button" :disabled="busy" @click="openDemo">
        Открыть демо-форму
      </button>
    </div>

    <p v-if="err" class="error">{{ err }}</p>
  </div>
</template>
