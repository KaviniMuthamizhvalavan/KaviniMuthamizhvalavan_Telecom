/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The app calls the FastAPI backend through this proxy, so the browser only ever talks to the Vite origin
// and the backend needs no CORS change. Override the target with VITE_API_TARGET (default: the usual port 8000).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_TARGET || 'http://127.0.0.1:8000'
  return {
    plugins: [react()],
    server: { port: 5173, strictPort: true, proxy: { '/api': { target, changeOrigin: true } } },
    preview: { port: 4173, proxy: { '/api': { target, changeOrigin: true } } },
    test: { globals: true, environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], css: false },
  }
})
