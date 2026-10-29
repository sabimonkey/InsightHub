import { Typography } from 'antd'

const { Text } = Typography

const STEPS = [
  { key: 'QUEUED', label: '已提交' },
  { key: 'PREPARING', label: '准备资料' },
  { key: 'CALLING_MODEL', label: 'AI 分析' },
  { key: 'VALIDATING', label: '核对来源' },
  { key: 'SAVING', label: '生成学习笔记' },
] as const

const ORDER = STEPS.map((item) => item.key)

function stepIndex(stage: string | null | undefined): number {
  if (!stage) return 0
  const idx = ORDER.indexOf(stage as typeof ORDER[number])
  return idx >= 0 ? idx : 0
}

type Props = {
  stage?: string | null
  stageLabel?: string | null
  providerHint?: string | null
}

export function AnalysisProgress({ stage, stageLabel, providerHint }: Props) {
  const current = stepIndex(stage)
  return (
    <div className="analysis-progress" aria-label="分析进度">
      <div className="analysis-progress-steps">
        {STEPS.map((item, index) => {
          const done = index < current
          const active = index === current
          return (
            <div key={item.key} className={`analysis-progress-step${active ? ' active' : ''}${done ? ' done' : ''}`}>
              <span className="analysis-progress-dot" aria-hidden>
                {done ? '✓' : active ? '●' : '○'}
              </span>
              <Text className="analysis-progress-label">{item.label}</Text>
              {index < STEPS.length - 1 ? <span className="analysis-progress-line" aria-hidden /> : null}
            </div>
          )
        })}
      </div>
      {stageLabel ? <Text type="secondary" className="analysis-progress-caption">{stageLabel}</Text> : null}
      {providerHint ? <Text type="secondary" className="meta-text">{providerHint}</Text> : null}
    </div>
  )
}
