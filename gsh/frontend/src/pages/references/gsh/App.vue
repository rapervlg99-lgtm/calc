<script setup lang="ts">
import { useScrollReveal } from '@/composables/useScrollReveal';
import LandingHeader from '@/components/landing/LandingHeader.vue';
import LandingFooter from '@/components/landing/LandingFooter.vue';
import GshTitleBand from '@/components/gsh/GshTitleBand.vue';
import GshScheme from '@/components/gsh/GshScheme.vue';
import GshConfigurator from '@/components/gsh/GshConfigurator.vue';
import GshHowItWorks from '@/components/gsh/GshHowItWorks.vue';
import GshSeoFaq from '@/components/gsh/GshSeoFaq.vue';
import GshCta from '@/components/gsh/GshCta.vue';

useScrollReveal(true);
</script>

<template>
  <div class="gsh-page">
    <LandingHeader active-nav="references" />
    <GshTitleBand />
    <GshScheme />
    <GshConfigurator />
    <GshHowItWorks />
    <GshSeoFaq />
    <GshCta />
    <LandingFooter />
  </div>
</template>
