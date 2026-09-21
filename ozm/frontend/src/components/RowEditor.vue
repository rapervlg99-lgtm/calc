<template>
  <Teleport to="body">
    <div v-if="open" class="row-editor-overlay" @click.self="$emit('close')">
      <div class="row-editor-sheet" role="dialog" aria-modal="true" aria-label="Правка строки">
        <div class="row-editor-sheet__head">
          <div>
            <h2 class="row-editor-sheet__title">Правка строки</h2>
            <p v-if="row?.name" class="row-editor-sheet__desc">{{ row.name }}</p>
          </div>
          <button type="button" class="btn-ghost btn-sm" @click="$emit('close')">Закрыть</button>
        </div>

        <form v-if="row" class="row-editor" @submit.prevent="save">
          <div class="row-editor__field">
            <span class="row-editor__label">Марка профиля</span>
            <!-- подсказки из справочника; выбор подставляет и массу 1 м -->
            <ProfileMarkInput
              v-model="form.profileMark"
              :prefer-category="category"
              aria-label="Марка профиля"
              @pick="onMarkPick"
            />
          </div>
          <label class="row-editor__field">
            <span class="row-editor__label">Конструкция</span>
            <select v-model="form.construction" class="cell-input">
              <option v-for="c in constructionChoices" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
          <label class="row-editor__field">
            <span class="row-editor__label">Длина, м</span>
            <input v-model="lengthStr" class="cell-input" inputmode="decimal" placeholder="1" />
          </label>
          <label class="row-editor__field">
            <span class="row-editor__label">Масса 1 пог. метра, кг</span>
            <input v-model="massPerMeterStr" class="cell-input" inputmode="decimal" placeholder="0" />
          </label>
          <label class="row-editor__field">
            <span class="row-editor__label">Классификация</span>
            <input v-model="form.classification" class="cell-input" />
          </label>

          <div class="row-editor__divider">Ручные атрибуты ОГЗ</div>

          <div class="row-editor__field">
            <span class="row-editor__label">Стороны обогрева</span>
            <HeatingSidesPicker v-model="form.heatingSides" />
          </div>

          <label class="row-editor__field">
            <span class="row-editor__label">Предел огнестойкости</span>
            <select v-model="form.fireLimit" class="cell-input" @change="onFireLimitSelect">
              <option value="">—</option>
              <option v-for="r in fireLimitChoices(form.fireLimit)" :key="r" :value="r">{{ r }}</option>
            </select>
          </label>

          <label class="row-editor__field">
            <span class="row-editor__label">Тип конструкции</span>
            <select v-model="form.bearingType" class="cell-input">
              <option value="">—</option>
              <option v-for="t in bearingTypeChoices(form.bearingType)" :key="t" :value="t">{{ t }}</option>
            </select>
          </label>

          <label class="row-editor__field">
            <span class="row-editor__label">Тип защитного покрытия</span>
            <select v-model="form.coatingType" class="cell-input">
              <option value="">—</option>
              <option
                v-for="t in coatingTypeChoices(form.coatingType, form.fireLimit)"
                :key="t"
                :value="t"
              >
                {{ t }}
              </option>
            </select>
          </label>

          <p v-if="error" class="row-editor__error">{{ error }}</p>
        </form>

        <div class="row-editor__actions">
          <button type="button" class="btn-ghost" @click="$emit('close')">Отмена</button>
          <button type="button" class="btn-primary" :disabled="saving" @click="save">Сохранить</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import HeatingSidesPicker from './HeatingSidesPicker.vue'
import ProfileMarkInput from './ProfileMarkInput.vue'
import { bearingTypeChoices } from '@/utils/bearingTypes'
import {
  coatingTypeChoices,
  isCoatingAvailableForFireLimit
} from '@/utils/coatingTypes'
import { fireLimitChoices } from '@/utils/fireLimits'
import { profileCategory } from '@/utils/ocrImport'
import { groupForCategory } from '@/utils/profileGroups'
import type { ProfileOption } from '@/utils/profileSuggest'
import type { OgzRow, OgzRowPatch } from '@/types/ogz'

const props = defineProps<{ open: boolean; row: OgzRow | null }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', rowId: number, patch: OgzRowPatch): void
}>()

const form = reactive({
  profileMark: '',
  construction: 'Балки',
  classification: '',
  heatingSides: '',
  fireLimit: '',
  bearingType: '',
  coatingType: ''
})
const massPerMeterStr = ref('')
const lengthStr = ref('')
const saving = ref(false)
const error = ref<string | null>(null)

const constructionChoices = [
  'Балки',
  'Ригели',
  'Колонны/Стойки',
  'Связи',
  'Прогоны'
]

// Вид профиля редактируемой строки — марки того же вида в подсказках первыми.
const category = computed(() =>
  props.row
    ? profileCategory(props.row.name || '', props.row.gostProfile || '', props.row.profileRaw || props.row.profileMark || '')
    : ''
)

/** Последний выбор из справочника — при сохранении по нему меняются наименование и ГОСТ группы. */
const pickedOption = ref<ProfileOption | null>(null)

/** Марка выбрана из справочника — масса 1 м подставляется, её можно поправить руками. */
function onMarkPick(option: ProfileOption): void {
  massPerMeterStr.value = String(option.massPerMeter)
  pickedOption.value = option
}

function onFireLimitSelect(): void {
  if (
    form.coatingType &&
    !isCoatingAvailableForFireLimit(form.coatingType, form.fireLimit)
  ) {
    form.coatingType = ''
  }
}

watch(
  () => props.row,
  (row) => {
    error.value = null
    pickedOption.value = null
    if (!row) return
    form.profileMark = row.profileMark
    form.construction = row.construction || 'Балки'
    form.classification = row.classification
    form.heatingSides = row.heatingSides.trim() || '4'
    form.fireLimit = row.fireLimit
    form.bearingType = row.bearingType
    form.coatingType = row.coatingType
    massPerMeterStr.value = row.massPerMeter ? String(row.massPerMeter) : ''
    lengthStr.value = row.lengthM ? String(row.lengthM) : ''
  },
  { immediate: true }
)

function save(): void {
  if (!props.row) return
  error.value = null
  const patch: OgzRowPatch = {
    profileMark: form.profileMark.trim(),
    construction: form.construction.trim(),
    classification: form.classification.trim(),
    heatingSides: form.heatingSides.trim(),
    fireLimit: form.fireLimit.trim(),
    bearingType: form.bearingType.trim(),
    coatingType: form.coatingType.trim()
  }
  // марка из справочника другого вида профиля — вместе с ней меняются
  // наименование группы и ГОСТ сортамента (двутавр → швеллер)
  const picked = pickedOption.value
  if (picked && picked.mark === patch.profileMark && picked.category && picked.category !== category.value) {
    const group = groupForCategory(picked.category, picked.mark)
    if (group) {
      patch.name = group.name
      patch.gostProfile = group.gost
    }
  }
  const rawMass = massPerMeterStr.value.trim().replace(',', '.')
  if (rawMass !== '') {
    const mass = Number(rawMass)
    if (!Number.isFinite(mass) || mass <= 0) {
      error.value = 'Масса должна быть положительным числом.'
      return
    }
    patch.massPerMeter = mass
  }
  const rawLen = lengthStr.value.trim().replace(',', '.')
  if (rawLen !== '') {
    const len = Number(rawLen)
    if (!Number.isFinite(len) || len < 0) {
      error.value = 'Длина должна быть неотрицательным числом.'
      return
    }
    patch.lengthM = len
  }
  saving.value = true
  emit('save', props.row.id, patch)
}

watch(
  () => props.open,
  (open) => {
    if (!open) saving.value = false
  }
)
</script>

<style scoped>
.row-editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  background: rgba(16, 24, 40, 0.35);
}

.row-editor-sheet {
  width: min(560px, 100%);
  max-height: min(92vh, 900px);
  overflow: auto;
  padding: 16px 16px 12px;
  border-radius: 16px 16px 0 0;
  background: var(--background-primary-a-enabled);
  box-shadow: 0 -8px 32px rgba(16, 24, 40, 0.18);
}

.row-editor-sheet__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.row-editor-sheet__title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.row-editor-sheet__desc {
  margin: 4px 0 0;
  color: var(--content-secondary-enabled);
  font-size: 13px;
}

.row-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px 0 8px;
}

.row-editor__divider {
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border-secondary-enabled);
  font-size: 13px;
  font-weight: 600;
  color: var(--content-secondary-enabled);
}

.row-editor__field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.row-editor__label {
  font-size: 13px;
  font-weight: 500;
  color: var(--content-secondary-enabled);
}

.row-editor__error {
  margin: 0;
  color: var(--content-system-negative);
}

.row-editor__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 0 4px;
}

@media (min-width: 720px) {
  .row-editor-overlay {
    align-items: center;
    padding: 24px;
  }

  .row-editor-sheet {
    border-radius: 16px;
  }
}
</style>
