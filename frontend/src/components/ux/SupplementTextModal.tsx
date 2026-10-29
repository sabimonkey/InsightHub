import { Alert, Button, Input, Modal, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { addUserTextSupplement } from '../../api'

const { Text } = Typography

type Props = {
  sourceId: string | null
  title?: string
  open: boolean
  onClose: () => void
  onDone?: () => void
}

export function SupplementTextModal({ sourceId, title, open, onClose, onDone }: Props) {
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) setText('')
  }, [open, sourceId])

  async function submit() {
    if (!sourceId || !text.trim() || saving) return
    setSaving(true)
    try {
      await addUserTextSupplement(sourceId, text)
      message.success('补充原文已保存；系统会标明为用户提供内容。')
      onDone?.()
      onClose()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存补充原文失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="补充 X 原文"
      open={open}
      onCancel={onClose}
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="save" type="primary" loading={saving} disabled={!text.trim()} onClick={() => void submit()}>
          保存补充内容
        </Button>,
      ]}
    >
      <p><Text strong>资料：</Text> {title || sourceId}</p>
      <Alert
        type="info"
        showIcon
        message="粘贴正文或截图 OCR 后的文字"
        description="内容会作为新的、可追溯的提取版本保存，并明确标记为用户提供；不会伪装成 X 自动抓取内容。保存后可从资料详情发起 AI 分析。"
        style={{ marginBottom: 12 }}
      />
      <Input.TextArea
        aria-label="补充 X 原文"
        value={text}
        onChange={(event) => setText(event.target.value)}
        autoSize={{ minRows: 8, maxRows: 16 }}
        maxLength={500_000}
        showCount
        placeholder="在此粘贴 X 正文或截图识别出的文字"
      />
    </Modal>
  )
}
