import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [react()],
  cacheDir: fileURLToPath(new URL('../../node_modules/.vite-workbench', import.meta.url)),
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  // API proxy is supplied by the root launcher, using its own Python child's actual port.
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    /* The third-party UI stack is one vendor chunk, so a rebuild reuses the cached chunk and the
       entry stays small. It is the Ant Design component set that makes it large (its icons tree-shake
       down to ~1 kB, and React rides along because Rolldown puts a dependency shared with the entry
       here); raising the warning limit records that this size is known instead of silencing it
       blindly — a future chunk regression would still show up. */
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        /* Vite 8 bundles with Rolldown, whose `manualChunks` accepts only the function form (Rollup's
           object form is rejected). `@xyflow/react` needs no rule: it only arrives through the
           graph's dynamic import, so it already gets its own on-demand chunk. */
        manualChunks(id) {
          return /\/node_modules\/(antd|@ant-design|@rc-component)\//.test(id.replace(/\\/g, '/')) ? 'vendor' : undefined;
        },
      },
    },
  },
});
