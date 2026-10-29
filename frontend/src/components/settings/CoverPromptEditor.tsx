import { useState } from 'react'
import { Button, Input, Modal, Select, Space, Typography } from 'antd'
import {
  fetchGlobalCoverPrompt,
  fetchLibrary,
  previewGlobalCoverPrompt,
  resetGlobalCoverPrompt,
  saveGlobalCoverPrompt,
  type GlobalCoverPromptConfig,
} from '../../api'

const { Text, Paragraph } = Typography

export function CoverPromptEditor() {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [config, setConfig] = useState<GlobalCoverPromptConfig | null>(null)
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState('')
  const [sources, setSources] = useState<Array<{ source_id: string; display_name?: string; title?: string }>>([])
  const [sourceId, setSourceId] = useState<string>()
  const [colorScheme, setColorScheme] = useState('auto')
  const [personalization, setPersonalization] = useState('')
  const [preview, setPreview] = useState<{ title?: string; topic?: string; palette_direction?: string; prompt?: string; prompt_char_count?: number; prompt_revision?: number; prompt_version?: string } | null>(null)

  async function openEditor(nextOpen: boolean) {
    if (!nextOpen || config || loading) return
    setLoading(true)
    try {
      const [current, library] = await Promise.all([fetchGlobalCoverPrompt(), fetchLibrary({ scope: 'mine' })])
      if (!current.ok) throw new Error(current.message || '无法读取全局配图 Prompt')
      setConfig(current)
      setDraft(current.prompt)
      setSources((library.items ?? []) as typeof sources)
    } catch (error) {
      setNote(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function save() {
    setSaving(true)
    setNote('')
    try {
      const result = await saveGlobalCoverPrompt(draft)
      if (!result.ok) throw new Error(result.message || result.code || '保存失败')
      setConfig(result)
      setDraft(result.prompt)
      setPreview(null)
      setNote(`已保存修订 ${result.revision}；后续新建任务立即使用。`)
    } catch (error) {
      setNote(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  function cancelChanges() {
    if (config) setDraft(config.prompt)
    setPreview(null)
    setNote('未保存修改已取消。')
  }

  function resetToDefault() {
    Modal.confirm({
      title: '恢复系统默认 Prompt？',
      content: '这会创建一个新的配置修订。当前和历史修订、封面任务及图片都会保留。',
      okText: '恢复默认', cancelText: '取消',
      onOk: async () => {
        setSaving(true)
        try {
          const result = await resetGlobalCoverPrompt()
          if (!result.ok) throw new Error(result.message || result.code || '恢复失败')
          setConfig(result)
          setDraft(result.prompt)
          setPreview(null)
          setNote(`已创建系统默认修订 ${result.revision}。`)
        } catch (error) {
          setNote(error instanceof Error ? error.message : '恢复失败')
        } finally {
          setSaving(false)
        }
      },
    })
  }

  async function previewPrompt() {
    if (!sourceId) {
      setNote('请选择一条资料后预览。')
      return
    }
    setSaving(true)
    setNote('')
    try {
      const result = await previewGlobalCoverPrompt({
        source_id: sourceId,
        global_prompt: draft,
        color_scheme: colorScheme,
        personalization,
      })
      if (!result.ok) throw new Error(result.message || result.code || '预览失败')
      setPreview(result)
    } catch (error) {
      setNote(error instanceof Error ? error.message : '预览失败')
    } finally {
      setSaving(false)
    }
  }

  const dirty = Boolean(config && draft !== config.prompt)
  return (
    <details onToggle={(event) => { void openEditor(event.currentTarget.open) }} style={{ marginTop: 14 }}>
      <summary style={{ cursor: 'pointer', fontWeight: 600 }}>全局配图 Prompt</summary>
      <div style={{ paddingTop: 12 }}>
        {loading ? <Text type="secondary">正在读取当前配置…</Text> : null}
        {config ? <div>
          <Space wrap style={{ marginBottom: 8 }}>
            <Text>当前修订：{config.revision} · {config.version}</Text>
            <Text type="secondary">上次修改：{config.updated_at ? new Date(config.updated_at).toLocaleString() : '—'}</Text>
            {dirty ? <Text type="warning">有未保存修改</Text> : null}
          </Space>
          <Input.TextArea
            aria-label="全局配图 Prompt"
            value={draft}
            onChange={(event) => { setDraft(event.target.value); setPreview(null) }}
            maxLength={config.max_global_prompt_chars}
            autoSize={{ minRows: 8, maxRows: 16 }}
            style={{ width: '100%', fontFamily: 'monospace' }}
          />
          <Text type="secondary" style={{ display: 'block', textAlign: 'right' }}>{Array.from(draft).length} / {config.max_global_prompt_chars} 字符</Text>
          <Text type="secondary">全局上限 {config.max_global_prompt_chars} 字符；最终发送给 image-01 的 Prompt 不超过 1500 字符。</Text>
          <Space wrap style={{ marginTop: 10 }}>
            <Button type="primary" disabled={!dirty} loading={saving} onClick={() => void save()}>保存修改</Button>
            <Button disabled={!dirty || saving} onClick={cancelChanges}>取消修改</Button>
            <Button disabled={saving} onClick={resetToDefault}>恢复系统默认</Button>
          </Space>
          <div style={{ marginTop: 18, borderTop: '1px solid rgba(0,0,0,0.08)', paddingTop: 14 }}>
            <Text strong>预览最终 Prompt</Text>
            <Paragraph type="secondary" style={{ marginBottom: 8 }}>预览使用后端生产构建逻辑，不创建 Cover Run，也不消耗配图额度。</Paragraph>
            <Space wrap style={{ width: '100%', marginBottom: 8 }}>
              <Select
                aria-label="预览资料"
                placeholder="选择一条资料"
                value={sourceId}
                onChange={(value) => { setSourceId(value); setPreview(null) }}
                options={sources.map((source) => ({ value: source.source_id, label: source.display_name || source.title || source.source_id }))}
                showSearch
                optionFilterProp="label"
                style={{ minWidth: 280 }}
              />
              <Select aria-label="预览配色" value={colorScheme} onChange={(value) => { setColorScheme(value); setPreview(null) }} options={[
                { value: 'auto', label: '自动配色' }, { value: 'cool', label: '冷色' }, { value: 'neutral', label: '中性' },
                { value: 'warm', label: '暖色' }, { value: 'high_contrast', label: '高对比' }, { value: 'low_saturation', label: '低饱和' }, { value: 'vivid', label: '鲜艳' },
              ]} style={{ minWidth: 130 }} />
              <Button loading={saving} onClick={() => void previewPrompt()}>预览最终 Prompt</Button>
            </Space>
            <Input.TextArea
              aria-label="本次个性化要求"
              placeholder="本次个性化要求（可选，仅用于预览/本次任务）"
              value={personalization}
              maxLength={160}
              onChange={(event) => { setPersonalization(event.target.value); setPreview(null) }}
              autoSize={{ minRows: 2, maxRows: 4 }}
            />
            <Text type="secondary" style={{ display: 'block', textAlign: 'right' }}>{Array.from(personalization).length} / 160 字符</Text>
            {preview ? <div style={{ marginTop: 10 }}>
              <Text type="secondary" style={{ display: 'block' }}>资料：{preview.title || '—'} · 主题：{preview.topic || '—'} · 配色方向：{preview.palette_direction || colorScheme} · Prompt 修订 {preview.prompt_revision} ({preview.prompt_version}) · {preview.prompt_char_count}/1500 字符</Text>
              <Input.TextArea aria-label="最终发送给 MiniMax 的 Prompt 预览" value={preview.prompt || ''} readOnly autoSize={{ minRows: 6, maxRows: 16 }} style={{ marginTop: 6, fontFamily: 'monospace' }} />
            </div> : null}
          </div>
          {note ? <Text type={note.includes('失败') || note.includes('不能') ? 'danger' : 'secondary'} style={{ display: 'block', marginTop: 8 }}>{note}</Text> : null}
        </div> : note ? <Text type="danger">{note}</Text> : null}
      </div>
    </details>
  )
}
