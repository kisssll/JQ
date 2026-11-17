// vite.config.js
import { defineConfig } from 'vite';
import path from 'path';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Бандл отдаётся из /static/dist, и base должен это повторять. Без него Vite
  // переписывал url() из CSS от корня сайта: шрифт, объявленный как
  // /static/fonts/rumi/manrope-cyrillic.woff2, превращался в /manrope-cyrillic.woff2,
  // то есть в 404, и страница тихо оставалась на системном шрифте.
  base: '/static/dist/',
  build: {
    // Папка, куда Vite сложит собранные файлы
    outDir: 'static/dist',
    // Очищать папку перед сборкой
    emptyOutDir: true,
    rollupOptions: {
      // Точки входа legacy-фронтенда и React-каталога спорта.
      input: {
        main: path.resolve(__dirname, 'static/src/js/main.js'),
        'sport-sparta': path.resolve(__dirname, 'static/src/sport/sparta/main.tsx'),
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