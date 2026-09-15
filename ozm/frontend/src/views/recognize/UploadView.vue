<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { APP_BASE } from '../../utils/api'
import { createExtJob, DEMO_JOB_ID, fetchMassHandbook, registerLocalJob } from '../../utils/extApi'
import { buildJobFromOcr, isOcrpdfResult } from '../../utils/ocrImport'
import { useCalcStore } from '../../stores/calc'
import { useJobStore } from '../../stores/job'

const router = useRouter()
const jobStore = useJobStore()
const calcStore = useCalcStore()
const busy = ref(false)
const err = ref('')
const dragOver = ref(false)
const importing = ref(false)
const frame = ref<HTMLIFrameElement | null>(null)

/**
 * Локальный OCR-сервис (ocrpdf). По умолчанию отдаётся тем же nginx под /ocr/
 * (см. frontend/nginx.conf и vite.config.ts); адрес можно переопределить
 * переменной VITE_OCR_URL. Параметр embed включает на странице OCR кнопку
 * «Передать в калькулятор огнезащиты».
 */
const OCR_URL = (import.meta.env.VITE_OCR_URL as string | undefined) || `${APP_BASE}ocr/`
const frameSrc = OCR_URL + (OCR_URL.includes('?') ? '&' : '?') + 'embed=1'

async function openDemo() {
  jobStore.openDemo()
  await router.push(`/recognize/jobs/${DEMO_JOB_ID}`)
}

async function onOcrMessage(e: MessageEvent) {
  if (!isOcrpdfResult(e.data)) return
  // принимаем результат только от нашего фрейма
  if (frame.value?.contentWindow && e.source !== frame.value.contentWindow) return
  if (importing.value) return
  err.value = ''
  importing.value = true
  try {
    if (!calcStore.dicts) await calcStore.loadDicts()
    const handbook = await fetchMassHandbook()
    const { job, notes } = buildJobFromOcr(e.data, {
      roll: calcStore.dicts?.roll || [],
      handbook
    })
    if (!job.profileRows.length && !job.sheetRows.length) {
      err.value = notes[0] || 'В распознанных таблицах нет строк спецификации с массами.'
      return
    }
    registerLocalJob(job)
    jobStore.setImportNotes(notes)
    await router.push(`/recognize/jobs/${job.id}`)
  } catch (e: any) {
    err.value = e?.message || 'Не удалось импортировать результат распознавания'
  } finally {
    importing.value = false
  }
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

onMounted(() => window.addEventListener('message', onOcrMessage))
onUnmounted(() => window.removeEventListener('message', onOcrMessage))
</script>

<template>
  <div class="ozm-page recognize-page">
    <div class="ozm-top">
      <h1 class="ozm-title">Распознать таблицу ИД</h1>
      <router-link class="btn-ghost" to="/">← К калькулятору</router-link>
    </div>

    <p class="recognize-lead">
      Загрузите PDF со спецификацией металлопроката в окно распознавания, проверьте, что
      выбран нужный файл, и нажмите «Распознать». Когда таблицы будут разобраны, нажмите
      там «Передать в калькулятор огнезащиты» — строки откроются в форме расчёта ОГЗ.
    </p>

    <div v-if="err" class="ocr-import-error" role="alert">
      <strong>Импорт не выполнен.</strong> {{ err }}
      <span class="muted">
        Форма ОГЗ открывается только для таблиц, опознанных как спецификация металлопроката:
        нужны колонки «№ п.п.», массы по элементам и «Общая масса». Проверьте в окне ниже,
        какого вида получилась таблица, и при необходимости загрузите PDF повторно с другим DPI.
      </span>
    </div>

    <div class="ocr-frame-wrap" :class="{ importing }">
      <iframe
        ref="frame"
        class="ocr-frame"
        :src="frameSrc"
        title="Распознавание таблиц из проектных PDF"
        allow="clipboard-write"
      />
      <div v-if="importing" class="ocr-frame-overlay">Импортируем строки…</div>
    </div>
    <p class="muted ocr-hint">
      Если окно пустое или показывает ошибку — локальный OCR-сервис не запущен
      (см. <code>dev/README.md</code>, раздел «OCR»).
    </p>

    <details class="ocr-alt">
      <summary>Другие способы</summary>
      <div
        class="dropzone"
        :class="{ over: dragOver, busy }"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="onDrop"
      >
        <p class="dropzone-title">{{ busy ? 'Загрузка…' : 'Распознать на сервере (Ollama)' }}</p>
        <p class="muted">Перетащите PDF сюда или выберите файл</p>
        <label class="btn-primary file-btn">
          Выбрать PDF
          <input type="file" accept="application/pdf,.pdf" :disabled="busy" @change="onInput" />
        </label>
      </div>
      <div class="page-actions" style="margin-top:16px">
        <button class="btn-add" type="button" :disabled="busy" @click="openDemo">
          Открыть демо-форму
        </button>
      </div>
    </details>
  </div>
</template>

<style scoped>
.ocr-frame-wrap {
  position: relative;
  border: 1px solid var(--line, #dfe3e8);
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
}
.ocr-frame {
  display: block;
  width: 100%;
  height: min(78vh, 1100px);
  min-height: 520px;
  border: 0;
}
.ocr-frame-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.75);
  font-weight: 600;
}
.ocr-hint {
  margin-top: 8px;
}
.ocr-import-error {
  border: 1px solid #e5534b;
  background: #fde8e9;
  color: #7a1c17;
  padding: 12px 16px;
  margin: 0 0 14px;
  border-radius: 8px;
  font-size: 14px;
}
.ocr-import-error .muted {
  display: block;
  margin-top: 6px;
  color: #7a1c17;
  opacity: 0.85;
  font-size: 13px;
}
.ocr-alt {
  margin-top: 24px;
}
.ocr-alt summary {
  cursor: pointer;
  margin-bottom: 12px;
}
</style>
