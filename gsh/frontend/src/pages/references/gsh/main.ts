import { createApp } from 'vue';
import { createRouter, createWebHistory } from 'vue-router';
import '@life_uikit/uikit/variables.css';
import '@life_uikit/uikit/fonts.css';

import { TnIconsPlugin } from '@/plugins/tn-icons';
import '../../../../../css/cl-combobox.css';
import '@/styles/global.css';
import '@/styles/landing.css';
import '@/styles/calculators.css';
import '@/styles/gsh.css';
import '@/styles/animations.css';

import App from './App.vue';

const router = createRouter({
  history: createWebHistory(),
  routes: [],
});

createApp(App).use(router).use(TnIconsPlugin).mount('#app');
