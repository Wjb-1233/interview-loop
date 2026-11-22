<script setup lang="ts">
import { computed, shallowRef } from 'vue'

import DashboardOverview from '@/components/dashboard/DashboardOverview.vue'
import DashboardGrowthPanel from '@/components/dashboard/DashboardGrowthPanel.vue'
import DashboardSummary from '@/components/dashboard/DashboardSummary.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useAuth } from '@/composables/useAuth'
import { useDashboard } from '@/composables/useDashboard'
import { api, errorMessage } from '@/lib/api'

const auth = useAuth()
const { data, loading, error, filters, load, updateFilters, resetFilters } = useDashboard()
const verifyBanner = computed(() => auth.user.value?.emailVerified === false)
const resendState = shallowRef('')
const resendBusy = shallowRef(false)
const today = computed(() => new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' }))

async function resendVerification() {
  if (resendBusy.value) return
  resendBusy.value = true
  try {
    const response = await api.post('/auth/verify-email/request')
    resendState.value = response.data.data.sent ? '验证邮件已发送，请查收' : '邮件服务未配置，请联系管理员'
  } catch (reason) { resendState.value = errorMessage(reason) }
  finally { resendBusy.value = false }
}

</script>

<template>
  <div class="page dashboard">
    <header class="page-head"><h1>成长看板</h1><span>{{ today }}</span></header>
    <section v-if="verifyBanner" class="verify-banner panel">
      <div><strong>还差一步：验证邮箱</strong><p>验证后即可开始训练。没收到邮件可以重新发送。</p></div>
      <button class="button secondary" type="button" :disabled="resendBusy" @click="resendVerification">{{ resendBusy ? '发送中…' : '重发验证邮件' }}</button><span>{{ resendState }}</span>
    </section>
    <div v-if="!data && error" class="error-banner" role="alert">{{ error }} <button class="button secondary" type="button" @click="load">重新加载</button></div>
    <div v-else-if="!data" class="skeleton loading" aria-label="正在加载训练概览" />
    <template v-else>
      <DashboardOverview :overview="data.overview" />
      <DashboardSummary v-if="data.summary" :summary="data.summary" />
      <EmptyState v-if="!data.overview.trainingCount" eyebrow="开始之前" title="先完成一场对练，建立你的成长起点" description="完成训练并获得正式评分后，看板会自动匹配相同条件的记录。先看本次报告，积累记录后再观察变化。" :steps="[{ title: '选择面试场景', detail: '按岗位和面试阶段开始' }, { title: '完成一次训练', detail: '文字、语音或视频都可以' }, { title: '学习后再复测', detail: '结合评分和原话证据看变化' }]" action-label="去选场景" action-to="/scenes" />
      <template v-else>
        <DashboardGrowthPanel :data="data" :filters="filters" :loading="loading" :error="error" @update="updateFilters" @reset="resetFilters" @retry="load" />
      </template>
    </template>
  </div>
</template>

<style scoped>
.dashboard { max-width:1040px; }.page-head { display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin-bottom:26px; }.page-head h1 { margin:0;font-size:clamp(28px,3.2vw,36px);font-weight:650;letter-spacing:-.02em; }.page-head span { font-size:12px;color:var(--text-3); }.loading { min-height:300px; }
.verify-banner { display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:18px;padding:14px 18px;border:1px solid var(--accent);background:var(--accent-soft); }.verify-banner strong { font-size:14px; }.verify-banner p,.verify-banner>span { color:var(--text-3);font-size:12px; }
</style>
