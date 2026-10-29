import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiPort = Number(process.env.INSIGHTHUB_E2E_API_PORT ?? 8090)

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': `http://127.0.0.1:${apiPort}`,
      '/health': `http://127.0.0.1:${apiPort}`,
    },
  },
})
