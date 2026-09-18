import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import {
  GSH_RAW_DATA,
  GSH_SPECIAL_PURPOSES,
  type GshRow,
  gshProductFullImgSrc,
  gshProductImgSrc,
  gshProductNodesSrc,
  stripHtml,
} from '@/data/gsh';
import { downloadGshPdf } from '@/lib/gsh-pdf-export';

export interface GshZoom {
  src: string;
  name: string;
  ekn: string;
}

function fieldMatches(rowVal: string, filterVal: string): boolean {
  if (filterVal.includes('/')) return rowVal === filterVal;
  if (rowVal.includes('/')) {
    return rowVal.split('/').map((s) => s.trim()).includes(filterVal);
  }
  return rowVal === filterVal;
}

function matchRow(row: GshRow, filters: Record<string, string>): boolean {
  for (const [key, val] of Object.entries(filters)) {
    if (!val) continue;
    const rv = (row[key as keyof GshRow] || '').trim();
    if (rv === '') continue;
    if (!fieldMatches(rv, val)) return false;
  }
  return true;
}

function findResults(filters: Record<string, string>): GshRow[] {
  return GSH_RAW_DATA.filter((row) => matchRow(row, filters));
}

function available(field: keyof GshRow, filters: Record<string, string>): string[] {
  const set = new Set<string>();
  GSH_RAW_DATA.filter((row) => matchRow(row, filters)).forEach((row) => {
    const v = (row[field] || '').trim();
    if (!v) return;
    if (v.includes('/')) {
      v.split('/').forEach((part) => set.add(part.trim()));
    } else {
      set.add(v);
    }
  });
  return [...set].sort();
}

function isSpecial(purpose: string): boolean {
  return (GSH_SPECIAL_PURPOSES as readonly string[]).includes(purpose);
}

export function useGshConfigurator() {
  const purpose = ref('');
  const seamType = ref('');
  const location = ref('');
  const clarification = ref('');
  const stage = ref('');
  const zoom = ref<GshZoom | null>(null);

  const sp = computed(() => isSpecial(purpose.value));
  const seamShown = computed(() => !!purpose.value && !sp.value);
  const seamTypeEff = computed(() => (seamShown.value ? seamType.value : ''));

  const locationState = computed(() => {
    let options: string[] = [];
    let disabled = true;
    let auto = false;
    let value = location.value;

    if (sp.value) {
      options = ['наружное'];
      disabled = true;
      auto = true;
      value = 'наружное';
    } else if (seamTypeEff.value) {
      options =
        seamTypeEff.value === 'технологический шов'
          ? ['внутреннее', 'наружное']
          : ['внутреннее', 'наружное', 'завершающая(П-образная)'];
      disabled = false;
    }

    return { options, disabled, auto, value };
  });

  const clarificationState = computed(() => {
    let options: string[] = [];
    let disabled = true;
    let auto = false;
    let label = 'Уточнение';
    let value = clarification.value;

    if (sp.value) {
      disabled = true;
      label = 'Уточнение (не требуется)';
      value = '';
    } else if (seamTypeEff.value) {
      label =
        seamTypeEff.value === 'технологический шов'
          ? 'Уточнение для тех. шва'
          : 'Уточнение для деф. шва';

      if (
        location.value === 'завершающая(П-образная)' &&
        seamTypeEff.value === 'деформационный шов'
      ) {
        options = ['ширина шва 50 мм'];
        value = 'ширина шва 50 мм';
        disabled = true;
        auto = true;
      } else if (location.value) {
        const cf = seamTypeEff.value === 'технологический шов' ? 'd' : 'e';
        options = available(cf, {
          a: purpose.value,
          b: seamTypeEff.value,
          c: location.value,
        });
        disabled = false;
      }
    }

    return { options, disabled, auto, label, value };
  });

  const stageState = computed(() => {
    const sf: Record<string, string> = {};
    if (purpose.value) sf.a = purpose.value;
    if (seamTypeEff.value && purpose.value === 'герметизация шва') sf.b = seamTypeEff.value;
    if (location.value) sf.c = location.value;
    const clarVal = clarificationState.value.value;
    if (clarVal && purpose.value === 'герметизация шва') {
      sf[seamTypeEff.value === 'технологический шов' ? 'd' : 'e'] = clarVal;
    }
    const options = available('f', sf);
    const disabled = sp.value ? !location.value : !clarVal;
    return { options, disabled };
  });

  const totalSteps = computed(() => (sp.value ? 3 : 5));

  const filledCount = computed(() => {
    let filled = 0;
    if (purpose.value) filled++;
    if (sp.value) {
      if (location.value) filled++;
      if (stage.value) filled++;
    } else {
      if (seamTypeEff.value) filled++;
      if (location.value) filled++;
      if (clarificationState.value.value) filled++;
      if (stage.value) filled++;
    }
    return filled;
  });

  const progressPct = computed(() => `${Math.round((filledCount.value / totalSteps.value) * 100)}%`);

  const allFilled = computed(() => {
    if (!purpose.value) return false;
    if (sp.value) return !!location.value && !!stage.value;
    return (
      !!seamTypeEff.value &&
      !!location.value &&
      !!clarificationState.value.value &&
      !!stage.value
    );
  });

  const filters = computed(() => {
    const f: Record<string, string> = {};
    if (purpose.value) f.a = purpose.value;
    if (seamTypeEff.value && purpose.value === 'герметизация шва') f.b = seamTypeEff.value;
    if (location.value) f.c = location.value;
    const clarVal = clarificationState.value.value;
    if (clarVal) {
      if (seamTypeEff.value === 'технологический шов') f.d = clarVal;
      else if (seamTypeEff.value === 'деформационный шов') f.e = clarVal;
    }
    if (stage.value) f.f = stage.value;
    return f;
  });

  const results = computed(() => findResults(filters.value));
  const showResults = computed(() => allFilled.value && results.value.length > 0);

  const paramTags = computed(() => {
    const tags: string[] = [];
    if (purpose.value) tags.push(purpose.value);
    if (seamTypeEff.value && purpose.value === 'герметизация шва') tags.push(seamTypeEff.value);
    if (location.value) tags.push(location.value);
    if (clarificationState.value.value && purpose.value === 'герметизация шва') {
      tags.push(clarificationState.value.value);
    }
    if (stage.value) tags.push(stage.value);
    return tags;
  });

  const emptyState = computed(() => {
    if (showResults.value) {
      return { icon: 'search', text: '' };
    }
    if (allFilled.value && results.value.length === 0) {
      return {
        icon: 'info',
        text: 'По заданным параметрам ничего не найдено. Попробуйте изменить критерии подбора.',
      };
    }
    if (purpose.value) {
      return {
        icon: 'filter-1',
        text: 'Продолжайте заполнять параметры — подходящие материалы появятся здесь.',
      };
    }
    return {
      icon: 'search',
      text: 'Заполните параметры подбора слева, чтобы увидеть подходящие гидрошпонки ТЕХНОНИКОЛЬ.',
    };
  });

  const resultSubtitle = computed(() =>
    showResults.value
      ? `${results.value.length} подходящих материалов`
      : 'Заполните параметры для подбора',
  );

  function onPurpose(v: string) {
    const isSp = isSpecial(v);
    purpose.value = v;
    seamType.value = '';
    location.value = isSp ? 'наружное' : '';
    clarification.value = '';
    stage.value = '';
  }

  function onSeam(v: string) {
    seamType.value = v;
    location.value = '';
    clarification.value = '';
    stage.value = '';
  }

  function onLocation(v: string) {
    const auto = v === 'завершающая(П-образная)' && seamType.value === 'деформационный шов';
    location.value = v;
    clarification.value = auto ? 'ширина шва 50 мм' : '';
    stage.value = '';
  }

  function onClarification(v: string) {
    clarification.value = v;
    stage.value = '';
  }

  function onStage(v: string) {
    stage.value = v;
  }

  function onReset() {
    purpose.value = '';
    seamType.value = '';
    location.value = '';
    clarification.value = '';
    stage.value = '';
  }

  function openZoom(row: GshRow) {
    zoom.value = {
      src: gshProductFullImgSrc(row.g),
      name: row.h,
      ekn: row.g,
    };
  }

  function closeZoom() {
    zoom.value = null;
  }

  function onExportPdf() {
    downloadGshPdf(
      {
        purpose: purpose.value,
        seamType: seamTypeEff.value,
        location: location.value,
        clarification: clarificationState.value.value,
        stage: stage.value,
      },
      results.value,
    ).catch(() => {
      // CDN недоступен — запасной вариант через печать страницы
      window.print();
    });
  }

  function hasImage(row: GshRow): boolean {
    return !!row.img;
  }

  function getThumbSrc(row: GshRow): string {
    return gshProductImgSrc(row.g);
  }

  function hasNodes(row: GshRow): boolean {
    return !!row.nodes;
  }

  function getNodesHref(row: GshRow): string {
    return gshProductNodesSrc(row.h);
  }

  function getNodesAbsHref(row: GshRow): string {
    return new URL(gshProductNodesSrc(row.h), window.location.origin).href;
  }

  let keyHandler: ((e: KeyboardEvent) => void) | null = null;

  onMounted(() => {
    keyHandler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && zoom.value) closeZoom();
    };
    window.addEventListener('keydown', keyHandler);
  });

  onBeforeUnmount(() => {
    if (keyHandler) window.removeEventListener('keydown', keyHandler);
  });

  return {
    purpose,
    seamType,
    location,
    clarification,
    stage,
    zoom,
    sp,
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
    printParams: computed(() => ({
      purpose: purpose.value,
      seamType: seamType.value,
      location: location.value,
      clarification: clarificationState.value.value,
      stage: stage.value,
    })),
  };
}
