import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // This config runs in Node. Only the proxy target is read; no secrets enter the bundle.
  const proxy = {
    '/api': { target: env.BACKEND_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
  }
  return {
    cacheDir: mode === 'faults' ? 'node_modules/.vite-faults' : 'node_modules/.vite',
    plugins: [react()],
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 4173, strictPort: true, proxy },
  }
})
