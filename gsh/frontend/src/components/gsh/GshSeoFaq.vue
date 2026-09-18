<script setup lang="ts">
import { GSH_FAQ } from '@/data/gsh';
</script>

<template>
  <section class="landing-container landing-seo gsh-seo" data-reveal data-noprint>
    <div class="landing-seo__grid">
      <div>
        <div class="landing-seo__eyebrow">О гидрошпонке</div>
        <h2 class="landing-seo__title">Подбор ПВХ-гидрошпонки для швов бетонных конструкций</h2>
        <p class="landing-seo__text">
          Гидрошпонка — профильный элемент из ПВХ для герметизации рабочих (технологических) и
          деформационных швов бетонных конструкций: фундаментов, стен подвалов, резервуаров и
          тоннелей. Она перекрывает путь воде по шву и сохраняет герметичность при подвижках и
          усадке бетона.
        </p>
        <p class="landing-seo__text landing-seo__text--muted">
          Конфигуратор CalcLab.pro подбирает марку гидрошпонки ТЕХНОНИКОЛЬ по назначению узла, типу
          и расположению шва, ширине раскрытия и стадии строительства. На выходе — конкретная марка,
          код ЕКН, ориентировочный расход и ссылка на технический лист для спецификации.
        </p>
      </div>
      <div>
        <h3 class="landing-faq__title">Частые вопросы</h3>
        <div class="landing-faq__list">
          <div v-for="item in GSH_FAQ" :key="item.question" class="landing-faq__item">
            <div class="landing-faq__question">{{ item.question }}</div>
            <p class="landing-faq__answer">{{ item.answer }}</p>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
