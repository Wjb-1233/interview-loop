<script setup lang="ts">
import { computed } from 'vue'

import MiniBarChart from './MiniBarChart.vue'
import MiniDonut from './MiniDonut.vue'
import MiniLineChart from './MiniLineChart.vue'

interface Metrics {
  evaluations: {
    total: number
    degraded: number
    degradedRatio: number
    avgDurationMs: number | null
    avgScore: number | null
    scoreBuckets: Record<string, number>
  }
  tasks: { total: number; byStatus: Record<string, number>; failedRatio: number }
  daily: Array<{ date: string; count: number }>
}

const props = defineProps<{ metrics: Metrics | null }>()

const BUCKETS = ['1-2', '3', '4', '5']
const DAILY_LIMIT = 14

function seconds(ms: number | null): string {
  if (!ms) return '—'
  return `${(ms / 1000).toFixed(1)}s`
}

const bucketItems = computed(() => {
  const buckets = props.metrics?.evaluations.scoreBuckets ?? {}
  return BUCKETS.map((key) => ({ label: `${key} 分`, value: buckets[key] ?? 0 }))
})
const bucketTotal = computed(() => bucketItems.value.reduce((sum, item) => sum + item.value, 0))

const dailyPoints = computed(() =>
  (props.metrics?.daily ?? []).slice(-DAILY_LIMIT).map((item) => ({ label: item.date.slice(5), value: item.count })),
)
const dailyTotal = computed(() => dailyPoints.value.reduce((sum, point) => sum + point.value, 0))

const evaluationTotal = computed(() => props.metrics?.evaluations.total ?? 0)
const degradedCount = computed(() => props.metrics?.evaluations.degraded ?? 0)
const taskTotal = computed(() => props.metrics?.tasks.total ?? 0)
const failedTasks = computed(() => props.metrics?.tasks.byStatus?.FAILED ?? 0)
</script>

<template>
  <section class="panel metrics-panel">
    <header class="metrics-head">
      <h2>运行指标</h2>
      <p>当前评分质量与历史录像分析结果。旧录像上传分析已停用。</p>
    </header>

    <p v-if="!metrics" class="metrics-empty">还没有统计数据</p>
    <template v-else>
      <div class="cards">
        <div class="card">
          <strong>{{ metrics.evaluations.total }}</strong>
          <span>评分总数</span>
        </div>
        <div class="card">
          <strong>{{ seconds(metrics.evaluations.avgDurationMs) }}</strong>
          <span>平均评分耗时</span>
        </div>
        <div class="card">
          <strong>{{ metrics.evaluations.avgScore ?? '—' }}</strong>
          <span>平均综合分</span>
        </div>
      </div>

      <div class="chart-grid">
        <section class="chart-card">
          <div class="chart-head">
            <h3>分数分布</h3>
            <span v-if="bucketTotal > 0">共 {{ bucketTotal }} 次评分</span>
          </div>
          <MiniBarChart v-if="bucketTotal > 0" :items="bucketItems" unit="次" />
          <p v-else class="chart-empty">还没有统计数据</p>
        </section>

        <section class="chart-card">
          <div class="chart-head">
            <h3>每日评分量</h3>
            <span v-if="dailyTotal > 0">最近 {{ dailyPoints.length }} 天</span>
          </div>
          <MiniLineChart v-if="dailyTotal > 0" :points="dailyPoints" :height="120" />
          <p v-else class="chart-empty">还没有统计数据</p>
        </section>

        <section class="chart-card span-2">
          <div class="chart-head">
            <h3>降级与失败</h3>
            <span v-if="evaluationTotal > 0 || taskTotal > 0">占各自总量比例</span>
          </div>
          <div v-if="evaluationTotal > 0 || taskTotal > 0" class="donuts">
            <MiniDonut v-if="evaluationTotal > 0" :value="degradedCount" :total="evaluationTotal" caption="降级" tone="warn" />
            <MiniDonut v-if="taskTotal > 0" :value="failedTasks" :total="taskTotal" caption="失败" tone="warn" />
          </div>
          <p v-else class="chart-empty">还没有统计数据</p>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.metrics-panel { padding: 22px; display: grid; gap: 16px; }
.metrics-head h2 { margin: 0 0 6px; font-family: var(--font-display); font-size: 20px; }
.metrics-head p { margin: 0; color: var(--text-2); font-size: 12.5px; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.card { padding: 13px 15px; border: 1px solid var(--line); border-radius: 12px; display: grid; gap: 4px; }
.card strong { font-size: 19px; line-height: 1.15; font-weight: 650; color: var(--text); font-variant-numeric: tabular-nums; }
.card span { color: var(--text-2); font-size: 11.5px; }
.chart-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
.chart-card { padding: 22px; border: 1px solid var(--line); border-radius: 14px; background: var(--overlay-1); display: grid; gap: 14px; align-content: start; }
.chart-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.chart-head h3 { margin: 0; font-size: 15px; font-weight: 650; color: var(--text); }
.chart-head span { color: var(--text-3); font-size: 11.5px; }
.donuts { display: flex; flex-wrap: wrap; align-items: center; gap: 26px; }
.chart-empty { margin: 0; padding: 22px 0; text-align: center; color: var(--text-3); font-size: 12.5px; }
.metrics-empty { margin: 0; padding: 26px 0; text-align: center; color: var(--text-3); font-size: 13px; }
@media (min-width: 1000px) {
  .chart-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .chart-card.span-2 { grid-column: 1 / -1; }
  .chart-card { padding: 24px; }
}
@media (max-width: 640px) {
  .cards { grid-template-columns: minmax(0, 1fr); }
}
</style>
