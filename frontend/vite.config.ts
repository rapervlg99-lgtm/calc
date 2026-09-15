/// <reference types="vitest/config" />
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const root = path.dirname(fileURLToPath(import.meta.url))

// Публичный префикс приложения. По умолчанию корень; на calclab.pro калькулятор
// живёт под /ozm/ (VITE_BASE_PATH=/ozm/ при сборке образа). Vite подставляет его
// в ссылки на бандлы и отдаёт коду как import.meta.env.BASE_URL — от него
// считаются роутер, /api и адрес OCR-фрейма.
const basePath = (process.env.VITE_BASE_PATH || '/').replace(/\/?$/, '/')

export default defineConfig({
  base: basePath,
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(root, 'src')
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8080',
      // локальный OCR-сервис (python webapp.py, порт 8000)
      '/ocr': {
        target: process.env.OCR_UPSTREAM || 'http://localhost:8000',
        rewrite: (p: string) => p.replace(/^\/ocr/, '') || '/',
        headers: { 'X-Forwarded-Prefix': '/ocr' }
      }
    }
  },
  test: {
    environment: 'node'
  }
})
