<script setup lang="ts">
import { shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorMessage } from '@/lib/api'
import type { ApiEnvelope } from '@/lib/types'
import type { TransferOverview } from '@/lib/contracts/interviewAssessment'
const props = defineProps<{ planId: string; transfer: TransferOverview }>()
const router = useRouter()
const busy = shallowRef(false)
const error = shallowRef('')
const labels: Record<string, string> = { INSUFFICIENT_SAMPLE: '样本不足', AWAITING_REVIEW: '待复核', INDEPENDENT_APPLICATION: '已体现独立应用', NEEDS_PRACTICE: '继续练习' }
async function start(): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const response = await api.post<ApiEnvelope<{ id: string }>>(`/training-plans/${props.planId}/transfer`)
    await router.push(`/training/${response.data.data.id}`)
  } catch (reason) { error.value = errorMessage(reason) }
  finally { busy.value = false }
}
</script>
<template>
  <section class="transfer-panel panel" aria-label="新题迁移验证">
    <div><p class="eyebrow">计划之后 · 独立应用</p><h2>换个情境，还能用出来吗？</h2><p>{{ transfer.reason }}</p></div>
    <button v-if="transfer.available" class="button" type="button" :disabled="busy" @click="start">{{ busy ? '准备新题…' : '开始新题迁移' }}</button>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <ul v-if="transfer.attempts.length"><li v-for="attempt in transfer.attempts" :key="attempt.sessionId">
      <RouterLink :to="attempt.status === 'ACTIVE' || !attempt.result ? `/training/${attempt.sessionId}` : `/report/${attempt.sessionId}`">{{ new Date(attempt.createdAt).toLocaleDateString('zh-CN') }} · {{ attempt.status === 'ACTIVE' ? '继续本次独立作答' : !attempt.result ? '继续生成本次报告' : labels[attempt.result] ?? '查看本次报告' }} →</RouterLink>
    </li></ul>
  </section>
</template>
<style scoped>
.transfer-panel { padding:24px 28px;margin:26px 0;display:flex;align-items:center;flex-wrap:wrap;gap:18px; }.transfer-panel>div { flex:1;min-width:400px; }.transfer-panel h2 { margin:0;font-size:20px; }.transfer-panel p:not(.eyebrow) { font-size:13px;color:var(--text-3);line-height:1.8; }.transfer-panel ul { width:100%;margin:0;padding:12px 0 0;list-style:none;border-top:1px solid var(--border); }.transfer-panel li { padding:7px 0;font-size:13px; }.transfer-panel a { color:var(--accent-strong); }
</style>
