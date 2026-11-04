import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Em desenvolvimento, /api e /media vão para o servidor Python do estúdio (padrão: 127.0.0.1:8765).
const target = process.env.BC_API || 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react()],
  server: {
    // o mapa (assets/maps/office.tmj) e os tilesets ficam fora de frontend/ (SPEC-VIS-001)
    fs: { allow: ['..'] },
    proxy: {
      '/api': { target, changeOrigin: true },
      '/media': { target, changeOrigin: true },
    },
  },
});
