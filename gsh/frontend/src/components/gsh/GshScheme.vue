<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { GSH_DIAGRAM_SRC, GSH_SCHEME_TAGS } from '@/data/gsh';

const zoomOpen = ref(false);
const zoomedIn = ref(false);
const lightboxEl = ref<HTMLElement | null>(null);

function openZoom() {
  zoomOpen.value = true;
  zoomedIn.value = false;
}

function closeZoom() {
  zoomOpen.value = false;
  zoomedIn.value = false;
}

function onImgClick(e: MouseEvent) {
  if (zoomedIn.value) {
    zoomedIn.value = false;
    return;
  }
  const img = e.currentTarget as HTMLImageElement;
  const rect = img.getBoundingClientRect();
  const relX = (e.clientX - rect.left) / rect.width;
  const relY = (e.clientY - rect.top) / rect.height;
  zoomedIn.value = true;
  nextTick(() => {
    const box = lightboxEl.value;
    if (!box) return;
    box.scrollLeft = relX * img.clientWidth - box.clientWidth / 2;
    box.scrollTop = relY * img.clientHeight - box.clientHeight / 2;
  });
}

let keyHandler: ((e: KeyboardEvent) => void) | null = null;

onMounted(() => {
  keyHandler = (e: KeyboardEvent) => {
    if (e.key === 'Escape' && zoomOpen.value) closeZoom();
  };
  window.addEventListener('keydown', keyHandler);
});

onBeforeUnmount(() => {
  if (keyHandler) window.removeEventListener('keydown', keyHandler);
});
</script>

<template>
  <section class="landing-container gsh-scheme" data-reveal>
    <div class="gsh-scheme__card">
      <div class="gsh-scheme__head">
        <div>
          <div class="gsh-scheme__eyebrow">Схема применения</div>
          <h2 class="gsh-scheme__title">Где какая гидрошпонка работает в узле</h2>
          <p class="gsh-scheme__lead">
            Разрез фундамента с типовыми узлами: секционирование, технологический и деформационный
            швы, П-образная лента и примыкание стена-плита. Ориентируйтесь по схеме, задавая
            параметры в конфигураторе ниже.
          </p>
        </div>
        <div class="gsh-scheme__tags">
          <span v-for="tag in GSH_SCHEME_TAGS" :key="tag" class="gsh-scheme__tag">
            <span class="gsh-scheme__tag-dot" aria-hidden="true" />
            {{ tag }}
          </span>
        </div>
      </div>
      <div class="gsh-scheme__img-wrap">
        <div
          class="gsh-scheme__img-frame"
          role="button"
          tabindex="0"
          title="Открыть схему в полном размере"
          @click="openZoom"
          @keydown.enter="openZoom"
          @keydown.space.prevent="openZoom"
        >
          <img
            :src="GSH_DIAGRAM_SRC"
            alt="Схема применения гидрошпонки ТЕХНОНИКОЛЬ в узле фундамента: секционирование, технологический и деформационный швы, П-образная лента, примыкание стена-плита"
            class="gsh-scheme__img"
          />
          <span class="gsh-scheme__zoom" aria-hidden="true" data-noprint>
            <TNIcon name="search" :size="18" />
          </span>
        </div>
      </div>
    </div>
  </section>

  <Teleport to="body">
    <div
      v-if="zoomOpen"
      ref="lightboxEl"
      class="gsh-lightbox gsh-scheme-lightbox"
      :class="{ 'gsh-scheme-lightbox--zoomed': zoomedIn }"
      data-noprint
      @click="closeZoom"
    >
      <button
        type="button"
        class="gsh-lightbox__close gsh-scheme-lightbox__close"
        title="Закрыть"
        @click.stop="closeZoom"
      >
        <TNIcon name="close" :size="20" />
      </button>
      <img
        :src="GSH_DIAGRAM_SRC"
        alt="Схема применения гидрошпонки ТЕХНОНИКОЛЬ в узле фундамента"
        class="gsh-scheme-lightbox__img"
        :class="{ 'gsh-scheme-lightbox__img--zoomed': zoomedIn }"
        :title="zoomedIn ? 'Уменьшить' : 'Приблизить это место'"
        @click.stop="onImgClick"
      />
    </div>
  </Teleport>
</template>
