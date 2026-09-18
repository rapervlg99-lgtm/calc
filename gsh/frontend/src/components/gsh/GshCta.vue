<script setup lang="ts">
import CtaProps from '@/components/landing/CtaProps.vue';
</script>

<template>
  <section class="landing-container landing-cta gsh-cta" data-reveal data-noprint>
    <div class="landing-cta__card">
      <div class="landing-cta__grid" aria-hidden="true" />
      <div class="landing-cta__glow" aria-hidden="true" />
      <CtaProps />
      <div class="landing-cta__content landing-cta__content--refs">
        <div>
          <h2 class="landing-cta__title">Другой узел гидроизоляции?</h2>
          <p class="landing-cta__text">
            В справочниках CalcLab — конфигураторы решений ТЕХНОНИКОЛЬ. Напишите, подбор какого
            материала добавить.
          </p>
        </div>
        <a href="/references" class="landing-cta__link-btn">
          Все справочники
          <TNIcon name="right-m" :size="18" />
        </a>
      </div>
    </div>
  </section>
</template>
