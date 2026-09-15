import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from './router'
import App from './App.vue'
// Дизайн-система TN Life: шрифты, токены, CSS компонентов; затем алиасы и стили страниц.
import './styles/tn/fonts.css'
import './styles/tn/tokens.css'
import './styles/tn/components.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/app.css'

const app = createApp(App)
app.use(createPinia())
// BASE_URL — префикс из vite `base` (/, или /ozm/ на calclab.pro)
app.use(createRouter({ history: createWebHistory(import.meta.env.BASE_URL), routes }))
app.mount('#app')
