import type { Scores } from './types'

export const channelLabels: Record<string, string> = { TEXT: '文字', VOICE: '语音', VIDEO: '视频' }
export const depthLabels: Record<string, string> = { STANDARD: '标准追问', THREE_LAYER: '三层深挖', PRESSURE: '压力追问' }
export function trainingDate(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
export interface DashboardReference {
  anchorSessionId: string
  sceneId: string
  sceneTitle: string
  channel: string
  depth: string
  mode: string
  hasResume: boolean
  hasJd: boolean
  trainedAt: string
}
export interface DashboardFilters { channel: string; sceneId: string; anchorSessionId: string }
export interface TrainingSummary {
  sampleCount: number
  text: string
  nextAction: string
  reportSummary: string | null
}
export interface DashboardData {
  summary: TrainingSummary
  overview: { trainingCount: number; recentTrainingCount: number; recentDays: number; channelCounts: Record<string, number> }
  condition: DashboardReference | null
  filterOptions: { scenes: Array<{ id: string; title: string }>; anchors: DashboardReference[] }
  formalEvaluationCount: number
  sampleCount: number
  recentSampleCount: number
  minimumTrendSamples: number
  trendReady: boolean
  latestScore: number | null
  latestSessionId: string | null
  latestTrainingAt: string | null
  recentAverage: number | null
  dimensions: Scores | null
  averageDimensions: Scores | null
  styleTags: string[]
  weaknesses: Array<{ dimension: string; averageScore: number; sampleCount: number }>
  trends: Array<{ sessionId: string; date: string; score: number; dimensions: Scores }>
  delivery: { sessionId: string; channel: string; speech: Record<string, number>; camera: Record<string, number> } | null
}
