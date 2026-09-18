<script setup lang="ts">
import { GSH_MARKING, GSH_MARKING_EXAMPLES, GSH_STEPS } from '@/data/gsh';
</script>

<template>
  <section class="landing-container gsh-how" data-reveal data-noprint>
    <div class="gsh-how__grid">
      <div>
        <div class="landing-seo__eyebrow">Как это работает</div>
        <h2 class="gsh-how__title">Пошаговый подбор гидрошпонки под узел</h2>
        <p class="gsh-how__lead">
          Конфигуратор ведёт вас по параметрам узла сверху вниз: каждый следующий список открывается
          только с корректными вариантами для уже выбранных условий. Часть полей заполняется
          автоматически — например, расположение для секционирования всегда наружное.
        </p>
        <div class="gsh-how__steps">
          <div v-for="s in GSH_STEPS" :key="s.n" class="gsh-how__step">
            <span class="gsh-how__step-num">{{ s.n }}</span>
            <div>
              <div class="gsh-how__step-title">{{ s.title }}</div>
              <div class="gsh-how__step-desc">{{ s.desc }}</div>
            </div>
          </div>
        </div>
      </div>
      <div class="gsh-how__marking">
        <div class="gsh-how__marking-grid" aria-hidden="true" />
        <div class="gsh-how__marking-inner">
          <div class="gsh-how__marking-eyebrow">Маркировка</div>
          <h3 class="gsh-how__marking-title">Как читать марку гидрошпонки</h3>
          <div class="gsh-how__marking-examples">
            <div v-for="ex in GSH_MARKING_EXAMPLES" :key="ex.label" class="gsh-how__marking-example">
              <div class="gsh-how__marking-example-mark">
                <span
                  v-for="seg in ex.segments"
                  :key="seg.part"
                  :class="['gsh-mark', `gsh-mark--${seg.part}`]"
                >{{ seg.text }}</span>
              </div>
              <div class="gsh-how__marking-example-label">{{ ex.label }}</div>
            </div>
          </div>
          <div class="gsh-how__marking-rows">
            <div v-for="m in GSH_MARKING" :key="m.code" class="gsh-how__marking-row">
              <span :class="['gsh-how__marking-code', 'gsh-mark', `gsh-mark--${m.part}`]">{{ m.code }}</span>
              <span class="gsh-how__marking-desc">{{ m.desc }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
