import { useState } from 'react'
import {
  addManualCandidate,
  analyzeSource,
  confirmCandidate,
  fetchAnalysis,
  fetchDiscovery,
  fetchOrganization,
  fetchSource,
  reanalyzeSource,
  reextractSource,
  rejectCandidate,
  startDiscovery,
} from '../api'
import type { AnalysisView, DiscoveryView, SourceDetail } from '../types'
import { SourceDetailDrawer } from './SourceDetailDrawer'

type Options = {
  onError?: (message: string) => void
}

export function useSourceDetailPanel({ onError }: Options = {}) {
  const [detail, setDetail] = useState<SourceDetail | null>(null)
  const [discovery, setDiscovery] = useState<DiscoveryView | null>(null)
  const [analysis, setAnalysis] = useState<AnalysisView | null>(null)
  const [organization, setOrganization] = useState<Awaited<ReturnType<typeof fetchOrganization>> | null>(null)
  const [open, setOpen] = useState(false)

  function report(caught: unknown, fallback: string) {
    onError?.(caught instanceof Error ? caught.message : fallback)
  }

  function openDetail(sourceId: string) {
    void Promise.all([fetchSource(sourceId), fetchDiscovery(sourceId), fetchAnalysis(sourceId)])
      .then(([body, found, analyzed]) => {
        setDetail(body)
        setDiscovery(found)
        setAnalysis(analyzed)
        setOpen(true)
        void fetchOrganization(sourceId).then(setOrganization).catch(() => setOrganization(null))
      })
      .catch((caught: unknown) => report(caught, '无法打开详情'))
  }

  const panel = (
    <SourceDetailDrawer
      open={open}
      detail={detail}
      discovery={discovery}
      analysis={analysis}
      organization={organization}
      onClose={() => setOpen(false)}
      onReextract={(sourceId) => {
        void reextractSource(sourceId)
          .then(() => fetchSource(sourceId))
          .then((body) => setDetail(body))
          .catch((caught: unknown) => report(caught, '重新提取失败'))
      }}
      onDiscover={(sourceId) => {
        void startDiscovery(sourceId)
          .then(async () => {
            for (let attempt = 0; attempt < 40; attempt += 1) {
              const found = await fetchDiscovery(sourceId)
              setDiscovery(found)
              if (found.run && found.run.status !== 'PENDING' && found.run.status !== 'RUNNING') {
                break
              }
              await new Promise((resolve) => setTimeout(resolve, 400))
            }
          })
          .catch((caught: unknown) => report(caught, '发现失败'))
      }}
      onConfirm={(candidateId) => {
        const sourceId = detail?.source.id
        if (!sourceId) return
        void confirmCandidate(candidateId)
          .then(() => fetchDiscovery(sourceId))
          .then((found) => setDiscovery(found))
          .catch((caught: unknown) => report(caught, '确认失败'))
      }}
      onReject={(candidateId) => {
        const sourceId = detail?.source.id
        if (!sourceId) return
        void rejectCandidate(candidateId)
          .then(() => fetchDiscovery(sourceId))
          .then((found) => setDiscovery(found))
          .catch((caught: unknown) => report(caught, '拒绝失败'))
      }}
      onManual={(sourceId, url) => {
        void addManualCandidate(sourceId, url)
          .then(() => fetchDiscovery(sourceId))
          .then((found) => setDiscovery(found))
          .catch((caught: unknown) => report(caught, '无法添加候选'))
      }}
      onOpenTarget={(sourceId) => {
        void Promise.all([fetchSource(sourceId), fetchDiscovery(sourceId), fetchAnalysis(sourceId)])
          .then(([body, found, analyzed]) => {
            setDetail(body)
            setDiscovery(found)
            setAnalysis(analyzed)
            void fetchOrganization(sourceId).then(setOrganization).catch(() => setOrganization(null))
          })
          .catch((caught: unknown) => report(caught, '无法打开目标资料'))
      }}
      onAnalyze={(sourceId) => {
        const action = analysis?.run ? reanalyzeSource : analyzeSource
        void action(sourceId)
          .then(async () => {
            for (let attempt = 0; attempt < 40; attempt += 1) {
              const found = await fetchAnalysis(sourceId)
              setAnalysis(found)
              if (found.run && found.run.status !== 'PENDING' && found.run.status !== 'RUNNING') {
                break
              }
              await new Promise((resolve) => setTimeout(resolve, 400))
            }
          })
          .catch((caught: unknown) => report(caught, '分析失败'))
      }}
      onSelectRun={(sourceId, runId) => {
        void fetchAnalysis(sourceId, runId)
          .then((found) => setAnalysis(found))
          .catch((caught: unknown) => report(caught, '无法打开分析历史'))
      }}
    />
  )

  return { openDetail, panel }
}
