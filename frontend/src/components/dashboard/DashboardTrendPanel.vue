<script setup lang="ts">
import ScoreTrend from '@/components/report/ScoreTrend.vue'
import { trainingDate } from '@/lib/dashboard'
import type { DashboardData } from '@/lib/dashboard'
defineProps<{ data: DashboardData }>()
</script>
<template>
  <section class="trend panel" aria-labelledby="growth-trend-title">
    <header><h3 id="growth-trend-title">同条件成绩趋势</h3><span>共 {{ data.formalEvaluationCount }} 次正式评分 · 展示最近 {{ data.sampleCount }} 次</span></header>
    <ScoreTrend v-if="data.trendReady" compact label="同条件正式评分趋势" :points="data.trends" />
    <p v-else class="insufficient" role="status">已有 {{ data.sampleCount }} 次同条件正式评分，至少 {{ data.minimumTrendSamples }} 次再展示趋势。记录不足，暂不判断成长。</p>
    <p class="boundary">题目变化和评分波动仍可能影响成绩，一次涨分不代表稳定提升。规则评分不计入这组趋势。</p>
    <details v-if="data.trends.length"><summary>查看这组训练记录</summary><ul><li v-for="point in [...data.trends].reverse()" :key="point.sessionId"><RouterLink :to="`/report/${point.sessionId}`">{{ trainingDate(point.date) }}<strong>{{ point.score }} 分</strong><span>查看报告 →</span></RouterLink></li></ul></details>
  </section>
</template>
<style scoped>
.trend { padding:22px;margin-top:24px; }header { display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;align-items:center; }h3 { margin:0;font-size:16px; }header span,.boundary { font-size:12px;color:var(--text-3);line-height:1.8; }.insufficient { margin:24px 0;padding:16px;background:var(--bg-2);font-size:13px;line-height:1.8; }summary { font-size:12px;cursor:pointer;color:var(--accent-strong); }ul { list-style:none;padding:0;margin:12px 0 0;max-height:260px;overflow:auto; }li a { display:flex;flex-wrap:wrap;gap:16px;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--divider);font-size:12px;color:var(--text-2); }li span { color:var(--accent-strong); }
</style>
