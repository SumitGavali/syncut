import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    // Flask backend (adjust the port if yours differs)
    proxy: { '/api': { target: 'http://127.0.0.1:5000', changeOrigin: true } },
  },
});
