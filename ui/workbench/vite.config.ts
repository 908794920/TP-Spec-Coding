import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [react()],
  cacheDir: fileURLToPath(new URL('../../node_modules/.vite-workbench', import.meta.url)),
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  // API proxy is supplied by the root launcher, using its own Python child's actual port.
  build: { outDir: 'dist', emptyOutDir: true },
});
