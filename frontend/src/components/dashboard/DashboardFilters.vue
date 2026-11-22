<script setup lang="ts">
import { channelLabels, depthLabels, trainingDate } from '@/lib/dashboard'
import type { DashboardData, DashboardFilters } from '@/lib/dashboard'
defineProps<{ filters: DashboardFilters; options: DashboardData['filterOptions']; loading: boolean }>()
defineEmits<{ update: [patch: Partial<DashboardFilters>]; reset: [] }>()
</script>
<template>
  <details class="comparison-filters">
    <summary>调整比较范围</summary>
    <p>默认参考最近完成的正式评分训练。修改方式或场景后，会重新匹配该范围内最近训练的条件。</p>
    <div class="filter-grid">
      <label>训练方式<select aria-label="比较训练方式" :value="filters.channel" class="field" @change="$emit('update', { channel: ($event.target as HTMLSelectElement).value })"><option value="">自动选择方式</option><option v-for="(label, key) in channelLabels" :key="key" :value="key">{{ label }}</option></select></label>
      <label>面试场景<select aria-label="比较面试场景" :value="filters.sceneId" class="field" @change="$emit('update', { sceneId: ($event.target as HTMLSelectElement).value })"><option value="">自动选择场景</option><option v-for="scene in options.scenes" :key="scene.id" :value="scene.id">{{ scene.title }}</option></select></label>
      <label class="reference">参考训练<select aria-label="参考训练" :value="filters.anchorSessionId" class="field" :disabled="loading" @change="$emit('update', { anchorSessionId: ($event.target as HTMLSelectElement).value })"><option value="">使用范围内最近一次</option><option v-for="item in options.anchors" :key="item.anchorSessionId" :value="item.anchorSessionId">{{ trainingDate(item.trainedAt) }} · {{ item.sceneTitle }} · {{ channelLabels[item.channel] }} · {{ depthLabels[item.depth] }}</option></select></label>
    </div>
    <button class="button secondary" type="button" @click="$emit('reset')">恢复自动匹配</button>
  </details>
</template>
<style scoped>
.comparison-filters { margin:16px 0 22px; }.comparison-filters summary { cursor:pointer;font-size:13px;color:var(--accent-strong); }.comparison-filters p { font-size:12px;color:var(--text-3);line-height:1.7; }.filter-grid { display:grid;grid-template-columns:1fr 1.4fr;gap:12px;margin-bottom:14px; }label { display:grid;gap:7px;font-size:12px;color:var(--text-2); }.reference { grid-column:1/-1; }select { min-width:0;width:100%; }
</style>
