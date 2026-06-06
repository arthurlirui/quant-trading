import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5190,
    host: '0.0.0.0',
    proxy: {
      '/api': { target: 'http://localhost:8003', changeOrigin: true },
      '/health': { target: 'http://localhost:8003', changeOrigin: true },
    },
  },
})
