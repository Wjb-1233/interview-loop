<script setup lang="ts">
import { channelLabels } from '@/lib/dashboard'
import type { DashboardData } from '@/lib/dashboard'
defineProps<{ overview: DashboardData['overview'] }>()
</script>
<template>
  <section class="overview" aria-labelledby="overview-title">
    <header><h2 id="overview-title">训练概览</h2></header>
    <dl class="overview-grid">
      <div class="panel"><dt>累计完成训练</dt><dd>{{ overview.trainingCount }}<small>次</small></dd></div>
      <div class="panel"><dt>近 {{ overview.recentDays }} 天完成</dt><dd>{{ overview.recentTrainingCount }}<small>次</small></dd></div>
      <div class="panel channels"><dt>累计训练方式分布</dt><dd><span v-for="(label, key) in channelLabels" :key="key">{{ label }} <b>{{ overview.channelCounts[key] ?? 0 }}</b> 次</span></dd></div>
    </dl>
  </section>
</template>
<style scoped>
header { margin-bottom:14px; }header h2 { margin:0;font-size:18px;font-weight:600; }
.overview-grid { display:grid;grid-template-columns:1fr 1fr 1.4fr;gap:14px;margin:0; }.overview-grid>div { padding:20px 24px; }dt { color:var(--text-3);font-size:12px; }dd { margin:14px 0 0;font-family:var(--font-num);font-size:32px; }small { margin-left:8px;font-size:12px;color:var(--text-3); }.channels dd { display:flex;flex-wrap:wrap;gap:12px;font-family:inherit;font-size:12px;color:var(--text-2); }.channels b { font-size:20px;font-weight:500;margin:0 3px; }
</style>
