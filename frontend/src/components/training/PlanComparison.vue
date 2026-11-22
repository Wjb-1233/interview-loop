<script setup lang="ts">
import type { ScoreComparison, Scores } from '@/lib/types'
defineProps<{ comparison: ScoreComparison; showReportLinks?: boolean }>()
const labels: Record<keyof Scores, string> = { logic: '内容与逻辑', relevance: '贴合问题', correctness: '信息完整', concision: '表达干净' }
</script>
<template>
  <section class="panel comparison"><h2>复测前后对比</h2><p>{{ comparison.baselineOverall }} → {{ comparison.retestOverall }} 分</p>
    <table><thead><tr><th>维度</th><th>训练前</th><th>复测后</th><th>变化</th></tr></thead><tbody><tr v-for="(label, key) in labels" :key="key"><th>{{ label }}</th><td>{{ comparison.baselineScores[key] }}</td><td>{{ comparison.retestScores[key] }}</td><td>{{ comparison.scoreDeltas[key] > 0 ? '+' : '' }}{{ comparison.scoreDeltas[key] }}</td></tr></tbody></table>
    <p>{{ comparison.recommendation }}</p>
    <div v-if="showReportLinks" class="report-links"><RouterLink :to="`/report/${comparison.baselineSessionId}`">查看原训练报告 →</RouterLink><RouterLink :to="`/report/${comparison.retestSessionId}`">查看复测报告 →</RouterLink></div>
  </section>
</template>
<style scoped>.comparison { margin-top: 24px; padding: 22px; }.comparison table { width: 100%; text-align: left; }.comparison th, .comparison td { padding: 8px; }.report-links { display:flex;flex-wrap:wrap;gap:18px;font-size:12px;color:var(--accent-strong); }</style>
