<script setup lang="ts">
import GshTitleScene from './GshTitleScene.vue';
</script>

<template>
  <section class="landing-container gsh-title-band" data-reveal data-noprint>
    <div>
      <nav class="calc-breadcrumbs" aria-label="Хлебные крошки">
        <a href="/">Главная</a>
        <span class="calc-breadcrumbs__sep">/</span>
        <a href="/references">Справочники</a>
        <span class="calc-breadcrumbs__sep">/</span>
        <span class="calc-breadcrumbs__current">Гидрошпонка</span>
      </nav>
      <div class="gsh-title-band__badge">
        <span class="gsh-title-band__badge-dot" aria-hidden="true" />
        Конфигуратор · Гидроизоляция
      </div>
      <h1 class="gsh-title-band__h1">Конфигуратор гидрошпонки</h1>
      <p class="gsh-title-band__lead">
        Подбор ПВХ-гидрошпонки ТЕХНОНИКОЛЬ для деформационных и рабочих швов бетонных конструкций.
        Задайте назначение узла, тип и расположение шва — конфигуратор выдаст марку, ЕКН, расход и
        техлист.
      </p>
    </div>
    <div class="gsh-title-band__scene" aria-hidden="true">
      <GshTitleScene />
    </div>
  </section>
</template>
