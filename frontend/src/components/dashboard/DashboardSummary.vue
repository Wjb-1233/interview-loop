<script setup lang="ts">
import type { TrainingSummary } from '@/lib/dashboard'
defineProps<{ summary: TrainingSummary }>()
</script>

<template>
  <section class="dashboard-summary panel" aria-labelledby="training-summary-title">
    <header class="summary-head">
      <h3 id="training-summary-title">训练总结</h3>
      <span>{{ summary.sampleCount ? `根据同条件近 ${summary.sampleCount} 次正式评分整理` : '等待正式评分' }}</span>
    </header>
    <p class="summary-text">{{ summary.text }}</p>
    <blockquote v-if="summary.reportSummary" class="report-excerpt">
      <span>最近一次复盘</span>
      <p>{{ summary.reportSummary }}</p>
    </blockquote>
    <p class="summary-action"><strong>下一次怎么练</strong>{{ summary.nextAction }}</p>
  </section>
</template>

<style scoped>
.dashboard-summary { padding:24px 28px; margin:18px 0 24px; }
.summary-head { display:flex; justify-content:space-between; align-items:baseline; gap:16px; }
.summary-head h3 { margin:0; font-size:16px; font-weight:600; }
.summary-head span { color:var(--text-3); font-size:11px; }
.summary-text { margin:16px 0; font-size:14px; line-height:1.9; color:var(--text-2); }
.report-excerpt { margin:16px 0; padding:12px 16px; border-left:3px solid var(--accent); background:var(--accent-soft); border-radius:0 8px 8px 0; }
.report-excerpt span { color:var(--accent-strong); font-size:11px; }
.report-excerpt p { margin:5px 0 0; font-size:13px; line-height:1.85; white-space:pre-line; overflow-wrap:anywhere; }
.summary-action { margin:16px 0 0; font-size:13px; line-height:1.8; color:var(--text-2); }
.summary-action strong { display:block; margin-bottom:5px; font-size:12px; color:var(--text); font-weight:600; }
</style>
