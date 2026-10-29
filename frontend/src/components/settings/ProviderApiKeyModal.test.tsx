import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProviderApiKeyModal } from './ProviderApiKeyModal'
import type { LlmProvider } from '../../types'

const baseProvider: LlmProvider = {
  id: 'p1',
  name: 'MiniMax',
  provider_type: 'MINIMAX_IMAGE',
  base_url: 'https://api.minimax.cn',
  model: 'image-01',
  is_local: false,
  configured: true,
  enabled: true,
  is_default: false,
  api_key_state: 'configured',
  credential_source: 'vault',
  credential_manageable: true,
  deployments: [],
}

describe('ProviderApiKeyModal', () => {
  it('uses password input and configured placeholder without echoing saved key', () => {
    render(<ProviderApiKeyModal open provider={baseProvider} onClose={() => undefined} onSaved={() => undefined} />)
    const input = screen.getByPlaceholderText('已配置，留空保持不变')
    expect(input.getAttribute('type')).toBe('password')
    expect(input).toHaveValue('')
  })

  it('uses password input type for new keys', () => {
    render(
      <ProviderApiKeyModal
        open
        provider={{ ...baseProvider, api_key_state: 'not_configured', configured: false, credential_source: 'none' }}
        onClose={() => undefined}
        onSaved={() => undefined}
      />,
    )
    expect(screen.getByPlaceholderText('粘贴 API Key').getAttribute('type')).toBe('password')
  })
})
