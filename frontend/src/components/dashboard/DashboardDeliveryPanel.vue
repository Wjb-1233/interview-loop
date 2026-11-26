<script setup lang="ts">
import { computed } from 'vue'
import type { DashboardData } from '@/lib/dashboard'
const props = defineProps<{ delivery: NonNullable<DashboardData['delivery']> }>()
const metrics = computed(() => {
  const speech = props.delivery.speech
  const camera = props.delivery.camera
  const values: Array<{ label: string; value: string }> = []
  if (speech.speechRate !== undefined) values.push({ label: '语速', value: `${Math.round(speech.speechRate)} 字/分` })
  if (speech.pauseCount !== undefined) values.push({ label: '停顿', value: `${speech.pauseCount} 次` })
  if (speech.longestPause !== undefined) values.push({ label: '最长停顿', value: `${speech.longestPause} 秒` })
  if (camera.faceRatio !== undefined) values.push({ label: '出镜率', value: `${Math.round(Math.min(1, camera.faceRatio) * 100)}%` })
  if (camera.eyeContactRatio !== undefined) values.push({ label: '看镜头比例', value: `${Math.round(Math.min(1, camera.eyeContactRatio) * 100)}%` })
  return values
})
</script>
<template>
  <section class="delivery panel" aria-labelledby="delivery-title">
    <h3 id="delivery-title">最近一次的语音与镜头表现</h3>
    <dl v-if="metrics.length"><div v-for="item in metrics" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl>
    <p v-else>这次训练没有可用的语音或镜头观测数据。</p>
    <RouterLink :to="`/report/${delivery.sessionId}`">查看本次报告与录制 →</RouterLink>
  </section>
</template>
<style scoped>
.delivery { margin-top:24px;padding:22px; }h3 { margin:0;font-size:16px; }p { color:var(--text-3);font-size:12px;line-height:1.8; }dl { display:flex;flex-wrap:wrap;gap:22px;margin:18px 0; }dt { color:var(--text-3);font-size:12px; }dd { margin:7px 0 0;font-size:20px; }a { color:var(--accent-strong);font-size:12px; }
</style>
