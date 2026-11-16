import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const target = process.env.AIR_API_TARGET ?? 'http://127.0.0.1:8000';
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': { target } } },
  preview: { proxy: { '/api': { target } } },
});

