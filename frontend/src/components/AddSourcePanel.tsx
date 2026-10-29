import { Alert, Button, Input, Tabs, Typography, Upload, message } from 'antd'
import type { UploadFile } from 'antd'
import type { RcFile } from 'antd/es/upload/interface'
import { useState } from 'react'
import { ingestFile, ingestFiles, ingestText, ingestUrl } from '../api'
import type { IngestResponse } from '../types'

const { TextArea } = Input

type AddSourcePanelProps = {
  onAdded: () => void
  variant?: 'default' | 'centered'
}

export function AddSourcePanel({ onAdded, variant = 'default' }: AddSourcePanelProps) {
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<IngestResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(action: () => Promise<IngestResponse | IngestResponse[]>) {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const outcome = await action()
      const last = Array.isArray(outcome) ? outcome[outcome.length - 1] : outcome
      setResult(last ?? null)
      if (Array.isArray(outcome) && outcome.some((item) => item.duplicate_detected)) {
        message.warning('部分文件已识别为重复资料，收集记录已保存。')
      }
      onAdded()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '保存失败')
      onAdded()
    } finally {
      setLoading(false)
    }
  }

  const panelClass = variant === 'centered' ? 'collection-add-panel collection-add-panel--centered' : 'collection-add-panel'

  return (
    <section className={panelClass} data-testid="add-source-panel">
      <Typography.Title level={5} style={{ marginTop: 0 }}>
        添加资料
      </Typography.Title>
      <Tabs
        items={[
          {
            key: 'url',
            label: 'URL',
            children: (
              <div className="add-row">
                <Input
                  aria-label="URL"
                  placeholder="粘贴网页、X、GitHub 等链接"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                />
                <Button
                  type="primary"
                  loading={loading}
                  onClick={() => {
                    void submit(async () => {
                      const response = await ingestUrl(url)
                      setUrl('')
                      return response
                    })
                  }}
                >
                  {loading ? '添加中…' : '添加'}
                </Button>
              </div>
            ),
          },
          {
            key: 'text',
            label: '文本',
            children: (
              <div className="add-column">
                <TextArea
                  aria-label="文本"
                  rows={5}
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  placeholder="粘贴需要保存的文本内容……"
                />
                <Button
                  type="primary"
                  loading={loading}
                  onClick={() => {
                    void submit(async () => {
                      const response = await ingestText(text)
                      setText('')
                      return response
                    })
                  }}
                >
                  {loading ? '添加中…' : '添加资料'}
                </Button>
              </div>
            ),
          },
          {
            key: 'file',
            label: '文件',
            children: (
              <div className="add-column">
                <Upload.Dragger
                  multiple
                  fileList={fileList}
                  beforeUpload={() => false}
                  onChange={({ fileList: next }) => setFileList(next)}
                >
                  <p>拖拽文件到这里，或点击选择。可以一次选择多个文件。</p>
                </Upload.Dragger>
                <Button
                  type="primary"
                  loading={loading}
                  disabled={fileList.length === 0}
                  onClick={() => {
                    const files = fileList
                      .map((item) => item.originFileObj)
                      .filter((item): item is RcFile => item instanceof File)
                    void submit(async () => {
                      const response = files.length === 1 ? await ingestFile(files[0]) : await ingestFiles(files)
                      setFileList([])
                      return response
                    })
                  }}
                >
                  {loading ? '上传/处理中…' : '添加'}
                </Button>
              </div>
            ),
          },
        ]}
      />
      {error ? <Alert type="error" showIcon title={error} /> : null}
      {result?.duplicate_detected ? (
        <Alert
          type="warning"
          showIcon
          title="已识别重复资料"
          description={
            <div>
              <div>已复用已有 Source</div>
              <div>本次收集记录已保存</div>
            </div>
          }
        />
      ) : null}
      {result && !result.duplicate_detected ? (
        <Alert type="success" showIcon title="资料已保存，正在提取正文。" />
      ) : null}
    </section>
  )
}
