import type { RouteRecordRaw } from 'vue-router'
import CalculatorView from '../views/CalculatorView.vue'
import UploadView from '../views/recognize/UploadView.vue'
import ProcessingView from '../views/recognize/ProcessingView.vue'
import OgzFormView from '../views/recognize/OgzFormView.vue'

export const routes: RouteRecordRaw[] = [
  { path: '/', component: CalculatorView },
  { path: '/recognize', component: UploadView },
  { path: '/recognize/jobs/:id/processing', component: ProcessingView },
  { path: '/recognize/jobs/:id', component: OgzFormView }
]
