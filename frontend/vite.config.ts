import path from 'node:path'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 产品版本唯一来源 = backend/pyproject.toml(见 Zeichen「版本策略」)。
const APP_VERSION = (() => {
  try {
    const text = readFileSync(
      fileURLToPath(new URL('../backend/pyproject.toml', import.meta.url)),
      'utf-8',
    )
    return text.match(/^version\s*=\s*"([^"]+)"/m)?.[1] ?? '0.0.0'
  } catch {
    return '0.0.0'
  }
})()

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': process.env.VITE_API_PROXY ?? 'http://localhost:8001',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
