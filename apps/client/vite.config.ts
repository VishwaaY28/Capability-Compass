import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'


export default defineConfig({
  base: '/Capability-Compass/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 8500,
    hmr: {
      path: '/Capability-Compass/@vite',
      host: '20.41.220.186',
      clientPort: 80,
      protocol: 'ws',
    },
    proxy: {
      '/Capability-Compass/api': {
        target: 'http://localhost:8005',
        changeOrigin: true,
        secure: false,
        rewrite: (p) => p.replace(/^\/Capability-Compass/, ''),
            },
    },
  },
});
