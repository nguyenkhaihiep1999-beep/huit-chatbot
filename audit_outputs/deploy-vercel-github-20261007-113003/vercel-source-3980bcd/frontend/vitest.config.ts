import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@hooks': fileURLToPath(new URL('./hooks', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    exclude: ['**/e2e/**', '**/node_modules/**'],
  },
});
