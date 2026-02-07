import { defineConfig } from 'vite';
import path from 'node:path';

export default defineConfig({
  base: '/output/assets/',
  build: {
    outDir: path.resolve(__dirname, 'output/assets'),
    emptyOutDir: false,
    cssCodeSplit: false,
    rollupOptions: {
      input: path.resolve(__dirname, 'frontend/src/main.ts'),
      output: {
        entryFileNames: 'curator.js',
        assetFileNames: () => 'curator.css',
      },
    },
  },
});
