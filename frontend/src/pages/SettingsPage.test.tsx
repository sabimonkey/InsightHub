import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SettingsPage } from './SettingsPage'

const localDeploymentId = '11111111-1111-1111-1111-111111111111'
const genericDeploymentId = '22222222-2222-2222-2222-222222222222'
const siliconDeploymentId = '33333333-3333-3333-3333-333333333333'

const routeRows = [
  {
    workflow: 'ANALYSIS',
    deployment_id: localDeploymentId,
    provider_type: 'LOCAL_OPENAI_COMPATIBLE',
    provider_name: 'LM Studio',
    deployment_display_name: 'qwen2.5-14b-instruct',
    model: 'qwen2.5-14b-instruct',
    label: 'LM Studio / qwen2.5-14b-instruct',
    is_local: true,
    configured: true,
    enabled: true,
  },
  {
    workflow: 'ASK_PLANNER',
    deployment_id: localDeploymentId,
    provider_type: 'LOCAL_OPENAI_COMPATIBLE',
    provider_name: 'LM Studio',
    deployment_display_name: 'qwen2.5-14b-instruct',
    model: 'qwen2.5-14b-instruct',
    label: 'LM Studio / qwen2.5-14b-instruct',
    is_local: true,
    configured: true,
    enabled: true,
  },
  {
    workflow: 'ASK_ANSWER',
    deployment_id: localDeploymentId,
    provider_type: 'LOCAL_OPENAI_COMPATIBLE',
    provider_name: 'LM Studio',
    deployment_display_name: 'qwen2.5-14b-instruct',
    model: 'qwen2.5-14b-instruct',
    label: 'LM Studio / qwen2.5-14b-instruct',
    is_local: true,
    configured: true,
    enabled: true,
  },
  {
    workflow: 'BRIEF',
    deployment_id: localDeploymentId,
    provider_type: 'LOCAL_OPENAI_COMPATIBLE',
    provider_name: 'LM Studio',
    deployment_display_name: 'qwen2.5-14b-instruct',
    model: 'qwen2.5-14b-instruct',
    label: 'LM Studio / qwen2.5-14b-instruct',
    is_local: true,
    configured: true,
    enabled: true,
  },
]

const routeOptions = [
  routeRows[0],
  {
    deployment_id: genericDeploymentId,
    provider_type: 'GENERIC_OPENAI_COMPATIBLE',
    provider_name: 'Generic',
    deployment_display_name: 'generic-model',
    model: 'generic-model',
    label: 'Generic / generic-model',
    is_local: false,
    configured: true,
    enabled: true,
  },
  {
    deployment_id: siliconDeploymentId,
    provider_type: 'SILICONFLOW',
    provider_name: 'SiliconFlow',
    deployment_display_name: 'sf-model',
    model: 'sf-model',
    label: 'SiliconFlow / sf-model',
    is_local: false,
    configured: true,
    enabled: false,
  },
]

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('SettingsPage', () => {
  it('shows keyless ZAI with both GLM models and a visible configuration-required state', async () => {
    const provider = {
      id: 'zai-1',
      name: '智谱 GLM',
      provider_type: 'ZAI',
      base_url: 'https://open.bigmodel.cn/api/paas/v4',
      model: 'glm-5.3-flash',
      is_local: false,
      configured: false,
      enabled: true,
      is_default: false,
      api_key_state: 'not_configured',
      credential_source: 'none',
      credential_manageable: true,
      deployments: [
        { id: 'zai-flash', display_name: 'GLM-5.3-Flash', model_id: 'glm-5.3-flash', enabled: false, route_ready: false },
        { id: 'zai-flashx', display_name: 'GLM-5.3-FlashX', model_id: 'glm-5.3-flashx', enabled: false, route_ready: false },
      ],
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/llm/providers')) return new Response(JSON.stringify([provider]), { headers: { 'Content-Type': 'application/json' } })
      if (url.includes('/api/llm/routes')) {
        return new Response(JSON.stringify({
          routes: [{ workflow: 'ANALYSIS', deployment_id: 'zai-flash', provider_type: 'ZAI', provider_name: '智谱 GLM', deployment_display_name: 'GLM-5.3-Flash', model: 'glm-5.3-flash', label: '智谱 GLM / GLM-5.3-Flash', is_local: false, configured: false, credential_configured: false, enabled: false, status: 'CONFIGURATION_REQUIRED' }],
          options: [],
        }), { headers: { 'Content-Type': 'application/json' } })
      }
      if (url.includes('/api/embedding/profiles')) return new Response(JSON.stringify({ profiles: [{ model: 'bge-m3-local', is_active: true }] }), { headers: { 'Content-Type': 'application/json' } })
      if (url.includes('/api/system')) return new Response(JSON.stringify({ optional: { embedding_configured: true, llm_configured: false }, counts: {}, disk: {}, alembic: {}, backend: 'ok', postgres: 'ok', redis: 'ok', worker: 'running', raw_storage: 'ok' }), { headers: { 'Content-Type': 'application/json' } })
      return new Response(JSON.stringify({}), { headers: { 'Content-Type': 'application/json' } })
    }))

    render(<SettingsPage section="models" onSectionChange={() => undefined} />)
    expect(await screen.findByLabelText('provider 智谱 GLM')).toBeTruthy()
    expect(screen.getByText('官方 GLM API · https://open.bigmodel.cn/api/paas/v4')).toBeTruthy()
    expect(screen.getByText('凭据来源：未配置')).toBeTruthy()
    expect(screen.getByText('glm-5.3-flash')).toBeTruthy()
    expect(screen.getByText('glm-5.3-flashx')).toBeTruthy()
    expect(screen.getByRole('button', { name: '配置 API 密钥' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '+ 添加模型' })).toBeEnabled()
  })

  it('shows system status, worker, disk warning, backup command, and version', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/api/llm/providers')) {
          return new Response(JSON.stringify([]), { headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/llm/routes')) {
          return new Response(JSON.stringify({ routes: [], options: [] }), { headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/embedding/profiles')) {
          return new Response(JSON.stringify({ profiles: [{ model: 'bge-m3-local', is_active: true }] }), { headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/system/recover') && init?.method === 'POST') {
          return new Response(JSON.stringify({ count: 1 }), { headers: { 'Content-Type': 'application/json' } })
        }
        return new Response(
          JSON.stringify({
            version: '1.0.0',
            backend: 'ok',
            postgres: 'ok',
            redis: 'ok',
            worker: 'not_detected',
            alembic: { revision: 'c8d2e5f03b19', ok: true },
            raw_storage: 'ok',
            disk: { path: 'G:\\data\\raw', used: 10, available: 1, warning: true },
            counts: { sources: 2, raw_files: 1, raw_bytes: 4, chunks: 3, claims: 1, embeddings: 0, briefs: 1 },
            optional: { llm_configured: false, embedding_configured: false },
            latest_backup: null,
            backup_command: 'scripts\\backup.ps1',
          }),
          { headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )
    const user = userEvent.setup()
    render(<SettingsPage section="runtime" onSectionChange={() => undefined} />)
    await user.click(await screen.findByText('高级系统信息'))
    expect(await screen.findByText('Version：1.0.0')).toBeTruthy()
    expect(screen.getByText('PostgreSQL：ok')).toBeTruthy()
    expect(screen.getByText(/后台任务/)).toBeTruthy()
    expect(screen.getByText('Worker：not_detected')).toBeTruthy()
    expect(screen.getByText('磁盘空间不足，未删除任何资料。')).toBeTruthy()
    expect(screen.getByText('Backup：scripts\\backup.ps1')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '恢复卡住的任务' }))
    expect(await screen.findByText('已恢复 1 个任务')).toBeTruthy()
    expect(screen.getAllByText(/BGE-M3/).length).toBeGreaterThan(0)
  })

  it('shows provider models, deployment routing labels, hides secrets, and saves routes', async () => {
    const providers = [
      {
        id: 'local-1',
        name: 'LM Studio',
        provider_type: 'LOCAL_OPENAI_COMPATIBLE',
        base_url: 'http://127.0.0.1:1234/v1',
        model: 'qwen2.5-14b-instruct',
        is_local: true,
        configured: true,
        enabled: true,
        is_default: true,
        api_key_state: 'not_required',
        deployments: [
          {
            id: localDeploymentId,
            display_name: 'qwen2.5-14b-instruct',
            model_id: 'qwen2.5-14b-instruct',
            enabled: true,
            route_ready: true,
          },
        ],
      },
      {
        id: 'cloud-1',
        name: 'DeepSeek',
        provider_type: 'DEEPSEEK',
        base_url: 'https://api.deepseek.com/v1',
        model: '',
        is_local: false,
        configured: false,
        enabled: true,
        is_default: false,
        api_key_state: 'not_configured',
        deployments: [],
      },
      {
        id: 'cloud-2',
        name: 'SiliconFlow',
        provider_type: 'SILICONFLOW',
        base_url: 'https://api.siliconflow.cn/v1',
        model: 'sf-model',
        is_local: false,
        configured: true,
        enabled: false,
        is_default: false,
        api_key_state: 'configured',
        deployments: [
          {
            id: siliconDeploymentId,
            display_name: 'sf-model',
            model_id: 'sf-model',
            enabled: false,
            route_ready: false,
          },
        ],
      },
      {
        id: 'cloud-3',
        name: 'Generic',
        provider_type: 'GENERIC_OPENAI_COMPATIBLE',
        base_url: 'https://example.invalid/v1',
        model: 'generic-model',
        is_local: false,
        configured: true,
        enabled: true,
        is_default: false,
        api_key_state: 'configured',
        deployments: [
          {
            id: genericDeploymentId,
            display_name: 'generic-model',
            model_id: 'generic-model',
            enabled: true,
            route_ready: true,
          },
        ],
      },
    ]
    const calls: Array<{ url: string; method?: string; body?: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push({ url, method: init?.method, body: typeof init?.body === 'string' ? init.body : undefined })
        if (url.includes('/api/llm/routes') && init?.method === 'PUT') {
          return new Response(JSON.stringify({ routes: routeRows, options: routeOptions }), { headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/llm/providers')) {
          return new Response(JSON.stringify(providers), { headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/llm/routes')) {
          return new Response(JSON.stringify({ routes: routeRows, options: routeOptions }), { headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/embedding/profiles')) {
          return new Response(JSON.stringify({ profiles: [{ model: 'bge-m3-local', dimensions: 1024, is_active: true }] }), { headers: { 'Content-Type': 'application/json' } })
        }
        return new Response(
          JSON.stringify({
            version: '1.0.0',
            backend: 'ok',
            postgres: 'ok',
            redis: 'ok',
            worker: 'running',
            alembic: { revision: 'e7f8a9b0c1d2', ok: true },
            raw_storage: 'ok',
            disk: { path: 'G:\\data\\raw', used: 1, available: 2, warning: false },
            counts: { sources: 0, raw_files: 0, raw_bytes: 0, chunks: 0, claims: 0, embeddings: 0, briefs: 0 },
            optional: { llm_configured: true, embedding_configured: true },
            latest_backup: null,
            backup_command: 'scripts\\backup.ps1',
          }),
          { headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )
    const user = userEvent.setup()
    render(<SettingsPage section="routes" onSectionChange={() => undefined} />)
    expect((await screen.findAllByText(/LM Studio/)).length).toBeGreaterThan(0)
    expect(document.body.textContent).not.toContain('sk-')
    const analysis = screen.getByLabelText('资料分析 route') as HTMLSelectElement
    expect(analysis.value).toBe(localDeploymentId)
    const silicon = Array.from(analysis.options).find((option) => option.value === siliconDeploymentId)
    expect(silicon?.disabled).toBe(true)
    await user.selectOptions(analysis, genericDeploymentId)
    expect(await screen.findByText('该工作流发送给模型的文本内容将提交到配置的外部 API。')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '保存任务模型路由' }))
    expect(await screen.findByText('AI Routing saved')).toBeTruthy()
    const saved = calls.find((item) => item.url.includes('/api/llm/routes') && item.method === 'PUT')
    expect(saved?.body).toContain(genericDeploymentId)
    expect(saved?.body).not.toContain('sk-')
  })

  it('shows capability probe details and edit model fields', async () => {
    const providers = [
      {
        id: 'local-1',
        name: 'LM Studio',
        provider_type: 'LOCAL_OPENAI_COMPATIBLE',
        base_url: 'http://127.0.0.1:1234/v1',
        model: 'qwen2.5-14b-instruct',
        is_local: true,
        configured: true,
        enabled: true,
        is_default: true,
        api_key_state: 'not_required',
        deployments: [
          {
            id: localDeploymentId,
            display_name: 'qwen2.5-14b-instruct',
            model_id: 'qwen2.5-14b-instruct',
            enabled: true,
            route_ready: true,
            capabilities: { supports_json_object: false, supports_json_schema: true },
          },
        ],
      },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes(`/api/llm/deployments/${localDeploymentId}/test`) && init?.method === 'POST') {
          return new Response(
            JSON.stringify({
              ok: true,
              overall_status: 'PASS',
              model: 'qwen2.5-14b-instruct',
              total_latency_ms: 120,
              probes: {
                chat: { status: 'SUPPORTED' },
                utf8: { status: 'SUPPORTED' },
                json_object: { status: 'UNSUPPORTED' },
                json_schema: { status: 'SUPPORTED' },
                streaming: { status: 'UNKNOWN' },
              },
            }),
            { headers: { 'Content-Type': 'application/json' } },
          )
        }
        if (url.includes('/api/llm/routes')) {
          return new Response(JSON.stringify({ routes: routeRows, options: routeOptions }), { headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/llm/providers')) {
          return new Response(JSON.stringify(providers), { headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/embedding/profiles')) {
          return new Response(JSON.stringify({ profiles: [{ model: 'bge-m3-local', is_active: true }] }), { headers: { 'Content-Type': 'application/json' } })
        }
        return new Response(
          JSON.stringify({
            version: '1.0.0',
            backend: 'ok',
            postgres: 'ok',
            redis: 'ok',
            worker: 'running',
            alembic: { revision: 'e7f8a9b0c1d2', ok: true },
            raw_storage: 'ok',
            disk: { path: 'G:\\data\\raw', used: 1, available: 2, warning: false },
            counts: { sources: 0, raw_files: 0, raw_bytes: 0, chunks: 0, claims: 0, embeddings: 0, briefs: 0 },
            optional: { llm_configured: true, embedding_configured: true },
            latest_backup: null,
            backup_command: 'scripts\\backup.ps1',
          }),
          { headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )
    const user = userEvent.setup()
    render(<SettingsPage section="models" onSectionChange={() => undefined} />)
    const modelCard = await screen.findByLabelText('model qwen2.5-14b-instruct')
    await user.click(within(modelCard).getByText('能力与技术详情'))
    expect(within(modelCard).getByText(/JSON Schema：支持/)).toBeTruthy()
    await user.click(within(modelCard).getByRole('button', { name: 'Test Model' }))
    expect(await screen.findByText(/JSON Object: UNSUPPORTED/)).toBeTruthy()
    expect(screen.getByText(/JSON Schema: SUPPORTED/)).toBeTruthy()
    await user.click(within(modelCard).getByRole('button', { name: 'Edit Model' }))
    expect((screen.getByLabelText('Model ID') as HTMLInputElement).readOnly).toBe(true)
    expect(screen.getByLabelText('Context Window')).toBeTruthy()
    expect(document.body.textContent).not.toContain('sk-')
  })
})
