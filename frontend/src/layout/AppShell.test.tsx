import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'

describe('AppShell license notice', () => {
  it('shows the warranty notice and links to this release license and source', () => {
    render(<AppShell view="library" onNavigate={vi.fn()}>content</AppShell>)

    expect(screen.getByText(/AGPL-3\.0-only.*不提供任何担保/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看许可证' })).toHaveAttribute('href', '/LICENSE')
    expect(screen.getByRole('link', { name: '对应源代码' })).toHaveAttribute(
      'href',
      'https://github.com/sabimonkey/InsightHub/tree/v1.0.0',
    )
  })
})
