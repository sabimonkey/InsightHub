import { Input, Modal, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import type { LlmProvider } from '../../types'
import { clearProviderCredential, saveProviderCredential } from '../../api'
import { credentialSourceLabel } from '../../lib/settingsModelStatus'

const { Text } = Typography

type Props = {
  open: boolean
  provider: LlmProvider | null
  onClose: () => void
  onSaved: () => void
}

export function ProviderApiKeyModal({ open, provider, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState('')
  const [visible, setVisible] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setDraft('')
      setVisible(false)
    }
  }, [open, provider?.id])

  if (!provider) return null
  const activeProvider = provider

  const configured = activeProvider.api_key_state === 'configured'
  const placeholder = configured ? '已配置，留空保持不变' : '粘贴 API Key'

  async function handleSave() {
    const trimmed = draft.trim()
    if (!trimmed) {
      message.info('请输入新的 API Key，或关闭对话框。')
      return
    }
    setSaving(true)
    try {
      await saveProviderCredential(activeProvider.id, trimmed)
      message.success('API Key 已安全保存')
      onSaved()
      onClose()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Modal
        title={`配置 ${activeProvider.name} API 密钥`}
        open={open}
        onCancel={onClose}
        okText="保存密钥"
        cancelText="取消"
        confirmLoading={saving}
        onOk={() => void handleSave()}
        destroyOnClose
      >
        <Text type="secondary">
          凭据来源：{credentialSourceLabel(activeProvider.credential_source)}。密钥仅保存在服务端加密存储，不会回显。
        </Text>
        <Input.Password
          className="provider-api-key-input"
          visibilityToggle={{ visible, onVisibleChange: setVisible }}
          placeholder={placeholder}
          value={draft}
          autoComplete="new-password"
          onChange={(event) => setDraft(event.target.value)}
        />
        {activeProvider.credential_source === 'environment' ? (
          <Text type="secondary">当前优先使用环境变量中的密钥；页面保存的密钥在环境变量未设置时生效。</Text>
        ) : null}
      </Modal>
    </>
  )
}

export function ClearProviderCredentialModal({
  open,
  provider,
  onClose,
  onCleared,
}: {
  open: boolean
  provider: LlmProvider | null
  onClose: () => void
  onCleared: () => void
}) {
  const [loading, setLoading] = useState(false)
  if (!provider) return null
  const providerId = provider.id

  async function handleClear() {
    setLoading(true)
    try {
      await clearProviderCredential(providerId)
      message.success('已清除页面保存的 API Key')
      onCleared()
      onClose()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '清除失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title="清除页面保存的 API Key？"
      open={open}
      onCancel={onClose}
      okText="确认清除"
      okButtonProps={{ danger: true, loading }}
      cancelText="取消"
      onOk={() => void handleClear()}
    >
      <Text>仅删除 InsightHub 加密 vault 中的密钥，不会修改 `.env` 或系统环境变量。</Text>
    </Modal>
  )
}

export function ProviderApiKeyActions({
  provider,
  onConfigure,
  onRequestClear,
}: {
  provider: LlmProvider
  onConfigure: () => void
  onRequestClear: () => void
}) {
  if (!provider.credential_manageable) return null
  return (
    <div className="provider-api-key-actions">
      <button type="button" className="provider-api-key-link" onClick={onConfigure}>
        配置 API 密钥
      </button>
      {provider.credential_source === 'vault' ? (
        <button type="button" className="provider-api-key-link provider-api-key-link--danger" onClick={onRequestClear}>
          清除密钥
        </button>
      ) : null}
    </div>
  )
}
