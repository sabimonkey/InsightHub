import { defineConfig, devices } from '@playwright/test'
import { resolve } from 'node:path'

const apiPort = Number(process.env.INSIGHTHUB_E2E_API_PORT ?? 8090)
const frontendPort = Number(process.env.INSIGHTHUB_E2E_FRONTEND_PORT ?? 5174)
const redisUrl = process.env.REDIS_URL ?? 'redis://127.0.0.1:6380/15'
const python = process.env.INSIGHTHUB_PYTHON ?? resolve(
  '..',
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)
const backend = resolve('..', 'backend')

export default defineConfig({
  testDir: './e2e',
  testIgnore: ['**/ask-real-streaming.spec.ts'],
  timeout: 60_000,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: backend,
      env: {
        PYTHONPATH: backend,
        INSIGHTHUB_SYSTEM_SCOPE: 'AUTOMATION_TEST',
        LLM_ENABLE_FAKE: 'true',
        LLM_DEFAULT_PROVIDER: 'FAKE',
        EMBEDDING_ENABLE_FAKE: 'true',
        MINIMAX_ENABLE_FAKE: 'true',
        COVER_INLINE: 'true',
        COVER_AUTO_ENABLED: 'false',
        PIPELINE_AUTO_ANALYSIS_ENABLED: 'false',
        EXTRACTION_INLINE: 'true',
        DISCOVERY_INLINE: 'true',
        ANALYSIS_INLINE: 'true',
        BRIEF_INLINE: process.env.BRIEF_INLINE ?? 'true',
        ASK_INLINE: 'true',
        ASK_FAKE_STREAM_CHUNK_MS: '80',
        REDIS_URL: redisUrl,
      },
      url: `http://127.0.0.1:${apiPort}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      cwd: '../frontend',
      env: { INSIGHTHUB_E2E_API_PORT: String(apiPort) },
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
})
