<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'

import MiniBarChart from '@/components/admin/MiniBarChart.vue'
import MiniLineChart from '@/components/admin/MiniLineChart.vue'
import { api, errorMessage } from '@/lib/api'
import type { AdminLearnerRow, ApiEnvelope } from '@/lib/types'

interface LearnerReport {
  learner: { id: string; name: string; email: string; active: boolean; bio?: string; avatar?: string | null; createdAt?: string | null }
  trainingCount: number
  evaluationCount: number
  averageScore: number
  dimensions: Record<string, number>
  weakestDimension: string | null
  styleTags: string[]
  trends: Array<{ date: string; score: number; dimensions: Record<string, number> }>
}

const DIMENSION_KEYS = ['logic', 'relevance', 'correctness', 'concision'] as const

const LABELS: Record<string, string> = {
  logic: '内容与逻辑',
  correctness: '信息完整',
  relevance: '贴合问题',
  concision: '表达干净',
}

const SUGGESTIONS: Record<string, string> = {
  logic: '先给结论，再补两条依据，说清因果与取舍。',
  correctness: '把关键事实说全：参与者、时间、数字、结果。',
  relevance: '先复述问题要点再回答，删掉与问题无关的铺垫。',
  concision: '每句话只承载一个信息，去掉重复与口头填充词。',
}

const route = useRoute()
const report = shallowRef<LearnerReport | null>(null)
const row = shallowRef<AdminLearnerRow | null>(null)
const loading = shallowRef(true)
const error = shallowRef('')
const exporting = shallowRef(false)

const hasScores = computed(() => (report.value?.evaluationCount ?? 0) > 0)
const dimensionItems = computed(() =>
  DIMENSION_KEYS.filter((key) => key in (report.value?.dimensions ?? {})).map((key) => ({
    label: LABELS[key],
    value: report.value!.dimensions[key],
  })),
)
const trendPoints = computed(() =>
  (report.value?.trends ?? []).slice(-14).map((point) => ({ label: point.date.slice(5), value: point.score })),
)
// 最新的一轮排在最前，方便从上往下读
const rounds = computed(() => {
  const trends = report.value?.trends ?? []
  return [...trends].reverse().map((point, index) => {
    const weakest = DIMENSION_KEYS.filter((key) => key in point.dimensions).sort(
      (left, right) => point.dimensions[left] - point.dimensions[right],
    )[0]
    return {
      key: `${point.date}-${index}`,
      round: trends.length - index,
      date: point.date,
      score: point.score,
      dimensions: DIMENSION_KEYS.filter((key) => key in point.dimensions).map((key) => ({
        label: LABELS[key],
        value: point.dimensions[key],
      })),
      advice: weakest ? SUGGESTIONS[weakest] : '',
      weakestLabel: weakest ? LABELS[weakest] : '',
    }
  })
})

function shortTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function load() {
  const id = String(route.params.id ?? '')
  if (!id) return
  loading.value = true
  error.value = ''
  try {
    const [reportResult, listResult] = await Promise.all([
      api.get<ApiEnvelope<LearnerReport>>(`/admin/learners/${id}/report`),
      // 概览卡要用训练场次/已完成/最近训练时间，这些字段只在概览列表里；缺失时降级用报告里的数字
      api.get<ApiEnvelope<AdminLearnerRow[]>>('/admin/learners').catch(() => null),
    ])
    report.value = reportResult.data.data
    row.value = listResult?.data.data.find((item) => item.userId === id) ?? null
  } catch (reason) {
    report.value = null
    row.value = null
    error.value = errorMessage(reason)
  } finally {
    loading.value = false
  }
}

async function exportReport() {
  const current = report.value
  if (!current || exporting.value) return
  exporting.value = true
  try {
    const response = await api.get<Blob>(`/admin/learners/${current.learner.id}/report/export`, { responseType: 'blob' })
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = `${current.learner.name}-能力报告.csv`
    link.click()
    URL.revokeObjectURL(url)
  } catch (reason) { error.value = errorMessage(reason) }
  finally { exporting.value = false }
}

watch(() => route.params.id, load, { immediate: true })
</script>

<template>
  <div class="page learner-page">
    <header class="page-heading learner-heading">
      <div>
        <RouterLink class="back-link" :to="{ name: 'admin' }">← 训练与报告</RouterLink>
        <p class="eyebrow">学员能力报告</p>
        <h1 class="page-title">{{ report?.learner.name ?? '学员详情' }}</h1>
        <p class="page-lead learner-meta">
          <template v-if="report">
            {{ report.learner.email }} · {{ report.learner.active ? '账号启用' : '账号停用' }}
          </template>
          <template v-else>查看这位学员的训练次数、四维能力与逐轮评分。</template>
        </p>
      </div>
      <button class="button" type="button" :disabled="!report || exporting" @click="exportReport">
        {{ exporting ? '导出中…' : '导出报告' }}
      </button>
    </header>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <div v-if="loading" class="panel loading" aria-label="正在加载学员报告">
      <div class="skeleton loading-line" />
      <div class="skeleton loading-line short" />
      <div class="skeleton loading-card" />
    </div>

    <template v-else-if="report">
      <section class="overview">
        <div class="panel card">
          <strong>{{ row ? row.sessions : report.trainingCount }}</strong>
          <span>训练场次</span>
        </div>
        <div class="panel card">
          <strong>{{ row ? row.finished : '—' }}</strong>
          <span>已完成</span>
        </div>
        <div class="panel card">
          <strong>{{ hasScores ? report.averageScore : '—' }}</strong>
          <span>平均分</span>
        </div>
        <div class="panel card">
          <strong class="card-time">{{ shortTime(row?.lastTrainedAt) }}</strong>
          <span>最近训练时间</span>
        </div>
      </section>

      <section class="panel block">
        <header class="block-head">
          <h2>四维能力平均分</h2>
          <span v-if="hasScores">满分 5 分 · 主要提升点：{{ report.weakestDimension ? (LABELS[report.weakestDimension] ?? report.weakestDimension) : '—' }}</span>
        </header>
        <MiniBarChart v-if="hasScores && dimensionItems.length" :items="dimensionItems" orientation="horizontal" unit=" 分" :max="5" />
        <p v-else class="empty">还没有评分数据</p>
      </section>

      <section class="panel block">
        <header class="block-head">
          <h2>近期评分趋势</h2>
          <span v-if="hasScores">最近 {{ trendPoints.length }} 次评分</span>
        </header>
        <MiniLineChart v-if="hasScores && trendPoints.length" :points="trendPoints" :height="150" />
        <p v-else class="empty">还没有评分数据</p>
      </section>

      <section class="panel block">
        <header class="block-head">
          <h2>逐轮批注与建议</h2>
          <span v-if="rounds.length">共 {{ rounds.length }} 轮，最新在前</span>
        </header>
        <div v-if="rounds.length" class="round-list">
          <article v-for="item in rounds" :key="item.key" class="round-card">
            <header class="round-head">
              <div>
                <p class="round-index">第 {{ item.round }} 轮</p>
                <p class="round-date">{{ item.date }}</p>
              </div>
              <span class="round-score">{{ item.score }}<small>分</small></span>
            </header>
            <dl class="round-dims">
              <div v-for="dimension in item.dimensions" :key="dimension.label">
                <dt>{{ dimension.label }}</dt>
                <dd>{{ dimension.value }}</dd>
              </div>
            </dl>
            <p v-if="item.advice" class="round-advice">建议 · 本轮短板 {{ item.weakestLabel }}：{{ item.advice }}</p>
          </article>
        </div>
        <p v-else class="empty">还没有评分数据</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.learner-page { max-width: 1100px; }
.learner-heading { align-items: flex-start; }
.back-link { display: inline-block; margin-bottom: 14px; color: var(--text-3); font-size: 12.5px; text-decoration: none; }
.back-link:hover { color: var(--text); }
.learner-heading .eyebrow { margin: 0; }
.learner-meta { margin-top: 8px; font-size: 13px; }

.overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
.card { display: flex; flex-direction: column; justify-content: space-between; gap: 10px; min-height: 104px; padding: 18px; }
.card strong { color: var(--text); font-family: var(--font-num); font-size: 28px; font-weight: 650; line-height: 1.1; }
.card .card-time { font-size: 20px; letter-spacing: -.01em; }
.card span { color: var(--text-3); font-size: 12.5px; }

.block { margin-bottom: 16px; padding: 20px 22px; }
.block-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.block-head h2 { margin: 0; color: var(--text); font-size: 14px; font-weight: 650; }
.block-head span { color: var(--text-3); font-size: 12px; }
.empty { margin: 0; padding: 26px 0; text-align: center; color: var(--text-3); font-size: 13px; }

.round-list { display: grid; gap: 10px; }
.round-card { padding: 14px 16px; border: 1px solid var(--divider); border-radius: 12px; background: var(--overlay-1); }
.round-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }
.round-index { margin: 0; color: var(--text-2); font-size: 13px; font-weight: 600; }
.round-date { margin: 3px 0 0; color: var(--text-3); font-size: 11.5px; }
.round-score { color: var(--text); font-family: var(--font-num); font-size: 20px; font-weight: 600; }
.round-score small { margin-left: 2px; color: var(--text-3); font-size: 11.5px; font-weight: 400; }
.round-dims { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 12px 0 0; }
.round-dims div { display: flex; align-items: baseline; gap: 6px; }
.round-dims dt { color: var(--text-3); font-size: 12px; }
.round-dims dd { margin: 0; color: var(--text-2); font-family: var(--font-num); font-size: 12.5px; }
.round-advice { margin: 10px 0 0; padding-top: 10px; border-top: 1px solid var(--divider); color: var(--text-3); font-size: 12.5px; line-height: 1.8; }

.loading { padding: 28px; display: grid; gap: 14px; }
.loading-line { height: 20px; width: 60%; }
.loading-line.short { width: 36%; }
.loading-card { height: 150px; width: 100%; }

@media (max-width: 960px) {
  .overview { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
