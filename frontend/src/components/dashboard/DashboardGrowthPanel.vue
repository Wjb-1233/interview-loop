<script setup lang="ts">
import { computed } from 'vue'
import DashboardAbilityPanel from './DashboardAbilityPanel.vue'
import DashboardScoreFeature from './DashboardScoreFeature.vue'
import DashboardFilters from './DashboardFilters.vue'
import DashboardTrendPanel from './DashboardTrendPanel.vue'
import DashboardDeliveryPanel from './DashboardDeliveryPanel.vue'
import { channelLabels, depthLabels } from '@/lib/dashboard'
import type { DashboardData, DashboardFilters as Filters } from '@/lib/dashboard'
const props = defineProps<{ data: DashboardData; filters: Filters; loading: boolean; error: string }>()
defineEmits<{ update: [patch: Partial<Filters>]; reset: []; retry: [] }>()
const focus = computed(() => props.data.weaknesses[0]?.dimension ?? (props.data.recentSampleCount ? '综合巩固' : '等待训练'))
</script>
<template>
  <section class="growth" aria-labelledby="growth-title" :aria-busy="loading">
    <header><h2 id="growth-title">同条件成长分析</h2></header>
    <DashboardFilters :filters="filters" :options="data.filterOptions" :loading="loading" @update="$emit('update', $event)" @reset="$emit('reset')" />
    <div v-if="error" class="error-banner" role="alert">{{ error }} <button type="button" class="button secondary" @click="$emit('retry')">重新加载</button></div>
    <p v-else-if="loading" class="scope panel" role="status">正在匹配可比较的训练记录…</p>
    <template v-else-if="data.condition && data.latestScore !== null">
      <div class="scope panel" role="status"><strong>{{ data.condition.sceneTitle }}</strong><p>{{ channelLabels[data.condition.channel] }} · {{ depthLabels[data.condition.depth] }} · {{ data.condition.mode === 'DRILL' ? '专项深挖模式' : '标准模式' }} · {{ data.condition.hasResume ? '沿用相同简历内容' : '未上传简历' }} · {{ data.condition.hasJd ? '沿用相同岗位 JD' : '未填写岗位 JD' }}</p><small>本组只包含条件一致的正式评分；参考训练决定分组，成绩取组内最近记录。</small></div>
      <DashboardScoreFeature :latest-score="data.latestScore" :latest-session-id="data.latestSessionId" :recent-average="data.recentAverage" :recent-sample-count="data.recentSampleCount" :focus="focus" :last-trained-at="data.latestTrainingAt" />
      <DashboardAbilityPanel v-if="data.averageDimensions" :scores="data.averageDimensions" :focus="focus" :sample-count="data.recentSampleCount" :weaknesses="data.weaknesses" />
      <DashboardTrendPanel :data="data" />
      <DashboardDeliveryPanel v-if="data.delivery" :delivery="data.delivery" />
    </template>
    <div v-else class="scope panel" role="status"><strong>这个范围内暂无正式评分</strong><p>可以恢复自动匹配，或完成一次新的训练。待重评、证据不足及规则评分保留在训练记录中，暂不参与成长统计。</p></div>
  </section>
</template>
<style scoped>
.growth { margin-top:34px; }header h2 { margin:0;font-size:18px;font-weight:600; }.scope { padding:18px 22px;margin-bottom:18px; }.scope strong { font-size:14px;font-weight:600; }.scope p { font-size:12px;line-height:1.8;margin:8px 0;color:var(--text-2); }.scope small { color:var(--text-3);font-size:11px; }.growth :deep(.ability) { margin-top:24px; }
</style>
