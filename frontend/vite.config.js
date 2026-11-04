import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Em desenvolvimento, /api e /media vão para o servidor Python do estúdio (padrão: 127.0.0.1:8765).
const target = process.env.BC_API || 'http://127.0.0.1:8765';
const rootDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(rootDir, './src'),
    },
  },
  server: {
    // o mapa (assets/maps/office.tmj) e os tilesets ficam fora de frontend/ (SPEC-VIS-001)
    fs: { allow: ['..'] },
    proxy: {
      '/api': { target, changeOrigin: true },
      '/media': { target, changeOrigin: true },
    },
  },
});
