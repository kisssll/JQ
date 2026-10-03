// vite.config.js
import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
  // Бандл отдаётся из /static/dist, и base должен это повторять. Без него Vite
  // переписывал url() из CSS от корня сайта: шрифт, объявленный как
  // /static/fonts/rumi/inter-cyrillic.woff2, превращался в /inter-cyrillic.woff2,
  // то есть в 404, и страница тихо оставалась на системном шрифте.
  base: '/static/dist/',
  build: {
    // Папка, куда Vite сложит собранные файлы
    outDir: 'static/dist',
    // Очищать папку перед сборкой
    emptyOutDir: true,
    rollupOptions: {
      // Точка входа – main.js
      input: {
        main: path.resolve(__dirname, 'static/src/js/main.js'),
      },
      output: {
        // Имена выходных файлов без хешей
        entryFileNames: '[name].js',
        chunkFileNames: '[name].js',
        assetFileNames: '[name].[ext]',
      },
    },
    // Минифицировать CSS (опционально)
    cssMinify: true,
  },
  // Опционально: сервер для разработки (пока не используем)
  server: {
    port: 5173,
    // Прокси для API, чтобы в dev-режиме запросы уходили на FastAPI
    proxy: {
      '/api': 'http://localhost:8000',
      '/static': 'http://localhost:8000',
    },
  },
});