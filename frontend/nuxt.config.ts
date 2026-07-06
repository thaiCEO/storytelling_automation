import { defineNuxtConfig } from 'nuxt/config'
import tailwindcss from '@tailwindcss/vite'

export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: false },
  css: ['~/assets/css/main.css'],
  vite: { plugins: [tailwindcss()] },
  routeRules: {
    '/': { redirect: '/create' },
  },
  nitro: {
    // dev proxy to the FastAPI backend
    devProxy: {
      '/api': { target: 'http://127.0.0.1:8000/api', changeOrigin: true },
      '/media': { target: 'http://127.0.0.1:8000/media', changeOrigin: true },
    },
  },
})
