<script setup lang="ts">
import ClCombobox from '@/components/shared/ClCombobox.vue';
import { GSH_PURPOSE_OPTIONS, GSH_SEAM_OPTIONS } from '@/data/gsh';
import { useGshConfigurator } from '@/composables/useGshConfigurator';

const {
  purpose,
  seamType,
  stage,
  zoom,
  seamShown,
  locationState,
  clarificationState,
  stageState,
  totalSteps,
  filledCount,
  progressPct,
  results,
  showResults,
  paramTags,
  emptyState,
  resultSubtitle,
  onPurpose,
  onSeam,
  onLocation,
  onClarification,
  onStage,
  onReset,
  openZoom,
  closeZoom,
  onExportPdf,
  hasImage,
  getThumbSrc,
  hasNodes,
  getNodesHref,
  getNodesAbsHref,
  stripHtml,
  printParams,
} = useGshConfigurator();
</script>

<template>
  <section class="landing-container gsh-config" data-reveal>
    <div class="gsh-config__grid">
      <div class="gsh-config__form" data-noprint>
        <div class="gsh-config__form-head">
          <span class="gsh-config__form-icon">
            <TNIcon name="protect" :size="24" />
          </span>
          <div>
            <div class="gsh-config__form-title">Параметры подбора</div>
            <div class="gsh-config__form-sub">
              Заполнено {{ filledCount }} из {{ totalSteps }}
            </div>
          </div>
        </div>

        <div class="gsh-config__progress">
          <div class="gsh-config__progress-fill" :style="{ width: progressPct }" />
        </div>

        <div class="gsh-field">
          <div class="gsh-field__label-row">
            <label class="gsh-field__label" for="gsh-purpose">Назначение</label>
            <span class="gsh-field__step">Шаг 1</span>
          </div>
          <div class="gsh-field__control">
            <ClCombobox
              input-id="gsh-purpose"
              variant="field"
              :model-value="purpose"
              :items="[...GSH_PURPOSE_OPTIONS]"
              placeholder="— Выберите назначение —"
              :searchable="false"
              input-class="cl-field__input cl-field__input--combo"
              @update:model-value="onPurpose"
            />
          </div>
        </div>

        <div v-if="seamShown" class="gsh-field">
          <div class="gsh-field__label-row">
            <label class="gsh-field__label" for="gsh-seam">Тип шва</label>
            <span class="gsh-field__step">Шаг 2</span>
          </div>
          <div class="gsh-field__control">
            <ClCombobox
              input-id="gsh-seam"
              variant="field"
              :model-value="seamType"
              :items="[...GSH_SEAM_OPTIONS]"
              placeholder="— Выберите тип шва —"
              :searchable="false"
              input-class="cl-field__input cl-field__input--combo"
              @update:model-value="onSeam"
            />
          </div>
        </div>

        <div class="gsh-field">
          <div class="gsh-field__label-row">
            <label class="gsh-field__label" for="gsh-location">
              Расположение
              <span v-if="locationState.auto" class="gsh-field__auto">авто</span>
            </label>
          </div>
          <div class="gsh-field__control">
            <ClCombobox
              input-id="gsh-location"
              variant="field"
              :model-value="locationState.value"
              :items="locationState.options"
              placeholder="— Выберите расположение —"
              :searchable="false"
              :disabled="locationState.disabled"
              input-class="cl-field__input cl-field__input--combo"
              @update:model-value="onLocation"
            />
          </div>
        </div>

        <div class="gsh-field">
          <div class="gsh-field__label-row">
            <label class="gsh-field__label" for="gsh-clar">
              {{ clarificationState.label }}
              <span v-if="clarificationState.auto" class="gsh-field__auto">авто</span>
            </label>
          </div>
          <div class="gsh-field__control">
            <ClCombobox
              input-id="gsh-clar"
              variant="field"
              :model-value="clarificationState.value"
              :items="clarificationState.options"
              placeholder="— Выберите уточнение —"
              :searchable="false"
              :disabled="clarificationState.disabled"
              input-class="cl-field__input cl-field__input--combo"
              @update:model-value="onClarification"
            />
          </div>
        </div>

        <div class="gsh-field">
          <div class="gsh-field__label-row">
            <label class="gsh-field__label" for="gsh-stage">Стадия строительства</label>
          </div>
          <div class="gsh-field__control">
            <ClCombobox
              input-id="gsh-stage"
              variant="field"
              :model-value="stage"
              :items="stageState.options"
              placeholder="— Выберите стадию —"
              :searchable="false"
              :disabled="stageState.disabled"
              input-class="cl-field__input cl-field__input--combo"
              @update:model-value="onStage"
            />
          </div>
        </div>

        <button type="button" class="gsh-config__reset" @click="onReset">
          <TNIcon name="repeat" :size="17" />
          Сбросить всё
        </button>
      </div>

      <div class="gsh-config__results">
        <div class="gsh-results__head">
          <div class="gsh-results__head-left">
            <span class="gsh-results__head-icon">
              <TNIcon name="protect" :size="23" />
            </span>
            <div>
              <div class="gsh-results__title">Результат подбора</div>
              <div class="gsh-results__sub">{{ resultSubtitle }}</div>
            </div>
          </div>
          <div v-if="showResults" class="gsh-results__actions" data-noprint>
            <span class="gsh-results__badge">
              <span class="gsh-results__badge-dot" aria-hidden="true" />
              Найдено: {{ results.length }}
            </span>
            <button type="button" class="gsh-results__pdf" @click="onExportPdf">
              <TNIcon name="pdf" :size="17" />
              Скачать отчёт PDF
            </button>
          </div>
        </div>

        <div v-if="showResults" class="gsh-results__params">
          <span class="gsh-results__params-label">Условия</span>
          <span v-for="p in paramTags" :key="p" class="gsh-results__param">{{ p }}</span>
        </div>

        <div v-if="showResults" class="gsh-results__cards">
          <article v-for="row in results" :key="row.g" class="gsh-result-card">
            <div v-if="hasImage(row)" class="gsh-result-card__img-wrap">
              <img
                :src="getThumbSrc(row)"
                :alt="row.h"
                loading="lazy"
                class="gsh-result-card__img"
              />
              <button
                type="button"
                class="gsh-result-card__zoom"
                title="Открыть все схемы стыковки"
                data-noprint
                @click.stop="openZoom(row)"
              >
                <TNIcon name="search" :size="16" />
              </button>
            </div>
            <div class="gsh-result-card__body">
              <span class="gsh-result-card__ekn">ЕКН {{ row.g }}</span>
              <component
                :is="row.k ? 'a' : 'div'"
                :href="row.k || undefined"
                :target="row.k ? '_blank' : undefined"
                :rel="row.k ? 'noopener' : undefined"
                class="gsh-result-card__name"
                :class="{ 'gsh-result-card__name--link': !!row.k }"
              >
                {{ row.h }}
              </component>
              <div class="gsh-result-card__consumption">
                <div class="gsh-result-card__meta">Расход на п.м</div>
                <div class="gsh-result-card__val" v-html="row.i" />
              </div>
              <div
                v-if="row.j && row.j !== '—'"
                class="gsh-result-card__comment"
              >
                <span class="gsh-result-card__meta">Особенности применения</span>
                <div v-html="row.j" />
              </div>
              <div class="gsh-result-card__links">
                <a
                  v-if="row.k"
                  :href="row.k"
                  target="_blank"
                  rel="noopener"
                  class="gsh-result-card__techlink"
                >
                  Открыть техлист
                  <TNIcon name="right-m" :size="16" />
                </a>
                <a
                  v-if="hasNodes(row)"
                  :href="getNodesHref(row)"
                  target="_blank"
                  rel="noopener"
                  class="gsh-result-card__techlink"
                >
                  Примеры узлов
                  <TNIcon name="right-m" :size="16" />
                </a>
              </div>
            </div>
          </article>
        </div>

        <div v-else-if="emptyState.text" class="gsh-results__empty">
          <span class="gsh-results__empty-icon">
            <TNIcon :name="emptyState.icon" :size="28" />
          </span>
          <p>{{ emptyState.text }}</p>
        </div>

        <p class="gsh-results__note">
          Конфигуратор на основе данных ТЕХНОНИКОЛЬ. Значения расхода указаны ориентировочно —
          уточняйте по техническому листу материала.
        </p>
      </div>
    </div>
  </section>

  <Teleport to="body">
    <div
      v-if="zoom"
      class="gsh-lightbox"
      data-noprint
      @click="closeZoom"
    >
      <div class="gsh-lightbox__card" @click.stop>
        <div class="gsh-lightbox__head">
          <div>
            <div class="gsh-lightbox__mono">Схемы стыковки · ЕКН {{ zoom.ekn }}</div>
            <div class="gsh-lightbox__title">{{ zoom.name }}</div>
          </div>
          <button type="button" class="gsh-lightbox__close" title="Закрыть" @click="closeZoom">
            <TNIcon name="close" :size="20" />
          </button>
        </div>
        <div class="gsh-lightbox__body">
          <img :src="zoom.src" :alt="zoom.name" class="gsh-lightbox__img" />
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div class="gsh-print-report" data-print-report>
    <div class="gsh-print-report__head">
      <span class="gsh-print-report__logo">CalcLab<span>.pro</span></span>
      <span class="gsh-print-report__subtitle">Отчёт по подбору гидрошпонки ТЕХНОНИКОЛЬ</span>
    </div>
    <h3 class="gsh-print-report__h">Исходные данные подбора</h3>
    <table class="gsh-print-report__table">
      <tbody>
        <tr>
          <td>Назначение</td>
          <td>{{ printParams.purpose || '—' }}</td>
        </tr>
        <tr>
          <td>Тип шва</td>
          <td>{{ printParams.seamType || '—' }}</td>
        </tr>
        <tr>
          <td>Расположение</td>
          <td>{{ printParams.location || '—' }}</td>
        </tr>
        <tr>
          <td>Уточнение</td>
          <td>{{ printParams.clarification || '—' }}</td>
        </tr>
        <tr>
          <td>Стадия строительства</td>
          <td>{{ printParams.stage || '—' }}</td>
        </tr>
      </tbody>
    </table>
    <h3 v-if="showResults" class="gsh-print-report__h">
      Результаты подбора · найдено {{ results.length }}
    </h3>
    <table v-if="showResults" class="gsh-print-report__table">
      <thead>
        <tr>
          <th>ЕКН</th>
          <th>Наименование</th>
          <th>Расход на п.м</th>
          <th>Особенности применения</th>
          <th>Документы</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in results" :key="row.g">
          <td>{{ row.g }}</td>
          <td>{{ row.h }}</td>
          <td>{{ stripHtml(row.i) }}</td>
          <td>{{ row.j ? stripHtml(row.j) : '—' }}</td>
          <td>
            <a v-if="row.k" :href="row.k" class="gsh-print-report__doclink">Техлист</a>
            <a v-if="hasNodes(row)" :href="getNodesAbsHref(row)" class="gsh-print-report__doclink">
              Примеры узлов
            </a>
            <template v-if="!row.k && !hasNodes(row)">—</template>
          </td>
        </tr>
      </tbody>
    </table>
    <div class="gsh-print-report__footer">
      ТЕХНОНИКОЛЬ · CalcLab.pro · значения расхода ориентировочные ·
      {{ new Date().toLocaleDateString('ru-RU') }}
    </div>
    </div>
  </Teleport>
</template>
