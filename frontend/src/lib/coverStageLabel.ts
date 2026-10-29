export function coverStageLabel(stage: string | undefined, status: string | undefined): string {
  const key = (stage || status || '').toUpperCase()
  switch (key) {
    case 'QUEUED':
      return '已提交，队列等待中…'
    case 'GENERATING':
      return '正在调用 MiniMax 生成…'
    case 'DECODING':
      return '正在解码图片…'
    case 'VALIDATING':
      return '正在校验图片…'
    case 'SAVING':
      return '正在保存封面…'
    case 'SUCCEEDED':
      return '生成成功'
    case 'FAILED':
      return '生成失败'
    default:
      return '处理中…'
  }
}
