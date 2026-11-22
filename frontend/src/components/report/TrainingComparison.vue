<script setup lang="ts">
import { computed, onMounted, shallowRef, watch } from 'vue'

import { api } from '@/lib/api'
import type { ApiEnvelope, Scores } from '@/lib/types'
import ScoreRadar from './ScoreRadar.vue'

interface Snapshot {
  sessionId: string
  sceneTitle: string
  channel: string
  startedAt: string
  overallScore: number | null
  scores: Scores
  answeredRounds: number
  speech: { avgRoundLength: number; avgSentenceLength: number; fillerRate: number; fillerTotal: number; flagCount: number }
}

interface DimensionRow { key: string; label: string; current: number; previous: number; delta: number }
interface MetricRow { key: string; label: string; unit: string; current: number; previous: number; delta: number; lowerIsBetter: boolean; neutral: boolean }
interface RoundRow { roundNo: number; currentChars: number; previousChars: number; currentFlags: number; previousFlags: number }

interface ComparisonView {
  scope: 'SAME_SCENE' | 'DIFFERENT_SCENE' | 'NONE'
  current: Snapshot | null
  previous: Snapshot | null
  dimensions: DimensionRow[]
  metrics: MetricRow[]
  improvements: Array<{ label: string; detail: string }>
  shortfalls: Array<{ label: string; detail: string }>
  summary: string
  rounds: RoundRow[]
}

const props = withDefaults(defineProps<{
  sessionId: string
  currentUrl?: string | null
  previousUrl?: string | null
  channel?: string
}>(), { currentUrl: null, previousUrl: null, channel: 'TEXT' })

const view = shallowRef<ComparisonView | null>(null)
const loading = shallowRef(true)
const failed = shallowRef(false)

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    const response = await api.get<ApiEnvelope<ComparisonView>>('/evaluations/' + props.sessionId + '/comparison')
    view.value = response.data.data
  } catch {
    failed.value = true
    view.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.sessionId, load)

const isVoice = computed(() => (props.channel ?? '').toUpperCase() === 'VOICE')
const hasRadar = computed(() => view.value?.scope === 'SAME_SCENE' && !!view.value?.current && !!view.value?.previous)
const scopeLabel = computed(() => {
  if (!view.value) return ''
  if (view.value.scope === 'SAME_SCENE') return '同一场景 · 四维与逐轮全方位对比'
  if (view.value.scope === 'DIFFERENT_SCENE') return '不同场景 · 只比通用指标'
  return '首次训练 · 暂无对比'
})

const overallNow = computed(() => view.value?.current?.overallScore ?? null)
const overallBefore = computed(() => view.value?.previous?.overallScore ?? null)
const overallDelta = computed(() => {
  if (overallNow.value === null || overallBefore.value === null) return 0
  return Math.round((overallNow.value - overallBefore.value) * 10) / 10
})
const overallDeltaText = computed(() => {
  if (overallNow.value === null || overallBefore.value === null) return '缺少对比'
  if (overallDelta.value === 0) return '持平'
  return (overallDelta.value > 0 ? '+' : '') + overallDelta.value + ' 分'
})

function overallWidth(value: number | null): string {
  if (value === null) return '0%'
  return Math.max(2, Math.min(100, Math.round(value))) + '%'
}

function dateText(snapshot: Snapshot | null): string {
  return snapshot ? new Date(snapshot.startedAt).toLocaleDateString('zh-CN') : ''
}

const maxMetric = computed(() => {
  const rows = view.value?.metrics ?? []
  const top = rows.reduce((acc, row) => Math.max(acc, row.current, row.previous), 0)
  return top > 0 ? top : 1
})

function barWidth(value: number): string {
  if (value <= 0) return '0%'
  return Math.max(3, Math.min(100, Math.round((value / maxMetric.value) * 100))) + '%'
}

function metricText(row: MetricRow, value: number): string {
  return row.unit === '%' ? value + '%' : value + (row.unit === '字' ? ' 字' : ' 次')
}

function deltaText(row: MetricRow): string {
  const delta = row.delta
  if (Math.abs(delta) < 0.05) return '持平'
  const sign = delta > 0 ? '+' : ''
  return sign + delta + (row.unit === '%' ? ' pt' : '')
}

function deltaClass(row: MetricRow): string {
  if (row.neutral || Math.abs(row.delta) < 0.05) return 'flat'
  const better = row.lowerIsBetter ? row.delta < 0 : row.delta > 0
  return better ? 'up' : 'down'
}

function dimensionDelta(row: DimensionRow): string {
  if (row.delta === 0) return '持平'
  return (row.delta > 0 ? '+' : '') + row.delta + ' 分'
}
</script>

<template>
  <section class="training-compare panel">
    <header>
      <h2>两次训练对比</h2>
      <span class="scope">{{ scopeLabel }}</span>
    </header>

    <p v-if="loading" class="hint">正在整理两次训练的差异…</p>
    <p v-else-if="failed" class="hint">对比数据暂时取不到，可以先看下面的录像与报告。</p>

    <template v-else-if="view">
      <p class="summary">{{ view.summary }}</p>

      <div class="compare-body" :class="{ single: !hasRadar }">
        <div v-if="hasRadar" class="chart-block">
          <ScoreRadar :scores="view.current!.scores" :previous="view.previous!.scores" />
          <ul class="legend">
            <li><i class="dot now" />本次 {{ overallNow ?? '—' }} 分 · {{ dateText(view.current) }}</li>
            <li><i class="dot before" />上次 {{ overallBefore ?? '—' }} 分 · {{ dateText(view.previous) }}</li>
          </ul>
        </div>

        <div class="body-col">
          <ul v-if="view.dimensions.length" class="dimension-list">
            <li v-for="row in view.dimensions" :key="row.key">
              <span class="name">{{ row.label }}</span>
              <span class="value">{{ row.previous }} → {{ row.current }}</span>
              <span class="chip" :class="row.delta > 0 ? 'up' : row.delta < 0 ? 'down' : 'flat'">{{ dimensionDelta(row) }}</span>
            </li>
          </ul>

          <div v-if="overallNow !== null || overallBefore !== null" class="overall-block">
            <div class="metric-head">
              <span class="name">综合评分</span>
              <span class="chip" :class="overallDelta > 0 ? 'up' : overallDelta < 0 ? 'down' : 'flat'">{{ overallDeltaText }}</span>
            </div>
            <div class="bar-row">
              <span class="tag">本次</span>
              <div class="bar"><span class="fill now" :style="{ width: overallWidth(overallNow) }" /></div>
              <b>{{ overallNow ?? '—' }}</b>
            </div>
            <div class="bar-row">
              <span class="tag">上次</span>
              <div class="bar"><span class="fill before" :style="{ width: overallWidth(overallBefore) }" /></div>
              <b>{{ overallBefore ?? '—' }}</b>
            </div>
          </div>
        </div>
      </div>

      <ul v-if="view.metrics.length" class="metric-list">
        <li v-for="row in view.metrics" :key="row.key">
          <div class="metric-head">
            <span class="name">{{ row.label }}</span>
            <span class="chip" :class="deltaClass(row)">{{ deltaText(row) }}</span>
          </div>
          <div class="bar-row">
            <span class="tag">本次</span>
            <div class="bar"><span class="fill now" :style="{ width: barWidth(row.current) }" /></div>
            <b>{{ metricText(row, row.current) }}</b>
          </div>
          <div class="bar-row">
            <span class="tag">上次</span>
            <div class="bar"><span class="fill before" :style="{ width: barWidth(row.previous) }" /></div>
            <b>{{ metricText(row, row.previous) }}</b>
          </div>
        </li>
      </ul>

      <div v-if="view.improvements.length || view.shortfalls.length" class="highlights">
        <section v-if="view.improvements.length" class="card up">
          <h3>这一次进步的地方</h3>
          <ul>
            <li v-for="item in view.improvements" :key="item.label">
              <strong>{{ item.label }}</strong><span>{{ item.detail }}</span>
            </li>
          </ul>
        </section>
        <section v-if="view.shortfalls.length" class="card down">
          <h3>还需要补的地方</h3>
          <ul>
            <li v-for="item in view.shortfalls" :key="item.label">
              <strong>{{ item.label }}</strong><span>{{ item.detail }}</span>
            </li>
          </ul>
        </section>
      </div>

      <table v-if="view.rounds.length" class="round-table">
        <caption>按轮对照</caption>
        <thead>
          <tr><th>轮次</th><th>本次字数</th><th>上次字数</th><th>本次表达提醒</th><th>上次表达提醒</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in view.rounds" :key="row.roundNo">
            <td>第 {{ row.roundNo }} 题</td>
            <td>{{ row.currentChars }}</td>
            <td>{{ row.previousChars }}</td>
            <td>{{ row.currentFlags }}</td>
            <td>{{ row.previousFlags }}</td>
          </tr>
        </tbody>
      </table>
    </template>

    <p v-else class="hint">还没有可以对比的上一场训练。完成下一场后，这里会给出进步与不足的分析。</p>

    <div v-if="currentUrl || previousUrl" class="media">
      <figure v-if="currentUrl">
        <video v-if="!isVoice" :src="currentUrl ?? undefined" controls preload="metadata" />
        <audio v-else :src="currentUrl ?? undefined" controls preload="metadata" />
        <figcaption><b>本次 {{ overallNow ?? '—' }}</b><span>{{ dateText(view?.current ?? null) }}</span></figcaption>
      </figure>
      <figure v-if="previousUrl">
        <video v-if="!isVoice" :src="previousUrl ?? undefined" controls preload="metadata" />
        <audio v-else :src="previousUrl ?? undefined" controls preload="metadata" />
        <figcaption><b>上次 {{ overallBefore ?? '—' }}</b><span>{{ dateText(view?.previous ?? null) }}</span></figcaption>
      </figure>
    </div>
  </section>
</template>

<style scoped>
.training-compare header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.training-compare h2 { font-size: 18px; font-weight: 600; margin: 0; }
.scope { color: var(--text-3); font-size: 12px; }
.hint { color: var(--text-3); font-size: 13px; margin: 12px 0 0; }
.summary { margin: 14px 0 0; font-size: 14px; line-height: 1.9; color: var(--text); }

.compare-body { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 30px; align-items: center; max-width: 880px; margin-top: 20px; }
.compare-body.single { grid-template-columns: minmax(0, 1fr); }
.chart-block { display: grid; gap: 10px; justify-items: center; padding: 0 14px 0 32px; }
.body-col { display: grid; gap: 20px; }
.legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 14px; margin: 0; padding: 0; list-style: none; color: var(--text-3); font-size: 11.5px; }
.legend .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.legend .dot.now { background: var(--radar-stroke); }
.legend .dot.before { background: transparent; border: 1.5px dashed var(--text-3); }

.dimension-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.metric-list { list-style: none; margin: 22px 0 0; padding: 0; display: grid; gap: 16px; max-width: 880px; }
.overall-block { display: grid; gap: 6px; }
.dimension-list li { display: grid; grid-template-columns: 96px auto 62px; justify-content: start; align-items: center; gap: 12px; font-size: 13px; padding: 5px 0; border-bottom: 1px solid var(--line, rgba(15, 23, 42, .06)); }
.dimension-list li:last-child { border-bottom: 0; }
.dimension-list .value { color: var(--text-3); font-variant-numeric: tabular-nums; }
.name { color: var(--text); }

.metric-head { display: flex; align-items: center; gap: 10px; font-size: 13px; margin-bottom: 6px; }
.bar-row { display: grid; grid-template-columns: 34px 1fr 48px; align-items: center; gap: 10px; font-size: 12px; color: var(--text-3); }
.bar-row .tag { white-space: nowrap; }
.bar-row b { text-align: right; font-weight: 500; color: var(--text-2, var(--text-3)); font-variant-numeric: tabular-nums; }
.bar { height: 8px; border-radius: 999px; background: var(--surface-2, rgba(15, 23, 42, .06)); overflow: hidden; }
.fill { display: block; height: 100%; border-radius: 999px; }
.fill.now { background: var(--accent, #2563eb); }
.fill.before { background: var(--text-3); opacity: .45; }

.chip { font-size: 12px; padding: 1px 8px; border-radius: 999px; white-space: nowrap; }
.chip.up { color: #0f7b4a; background: rgba(16, 185, 129, .12); }
.chip.down { color: #b42318; background: rgba(239, 68, 68, .12); }
.chip.flat { color: var(--text-3); background: rgba(100, 116, 139, .12); }

.highlights { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 18px; }
.card { border-radius: 12px; padding: 14px 16px; border: 1px solid var(--line, rgba(15, 23, 42, .08)); }
.card h3 { margin: 0 0 8px; font-size: 13px; font-weight: 600; }
.card.up { background: rgba(16, 185, 129, .06); }
.card.down { background: rgba(239, 68, 68, .05); }
.card ul { margin: 0; padding-left: 16px; display: grid; gap: 6px; }
.card li { font-size: 12.5px; line-height: 1.7; }
.card li strong { margin-right: 6px; }
.card li span { color: var(--text-3); }

.round-table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 12.5px; }
.round-table caption { text-align: left; color: var(--text-3); font-size: 12px; padding-bottom: 6px; }
.round-table th, .round-table td { border-bottom: 1px solid var(--line, rgba(15, 23, 42, .08)); padding: 7px 8px; text-align: right; font-variant-numeric: tabular-nums; }
.round-table th { color: var(--text-3); font-weight: 500; }
.round-table th:first-child, .round-table td:first-child { text-align: left; }

.media { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 18px; }
.media figure { margin: 0; display: grid; gap: 6px; }
.media video, .media audio { width: 100%; border-radius: 10px; background: #0b0b0e; }
.media audio { background: transparent; }
.media figcaption { display: flex; align-items: baseline; justify-content: space-between; color: var(--text-3); font-size: 11.5px; }
.media figcaption b { color: var(--text); font-size: 13px; }

@media (max-width: 900px) {
  .compare-body, .compare-body.single { grid-template-columns: minmax(0, 1fr); }
  .highlights, .media { grid-template-columns: 1fr; }
}
</style>
