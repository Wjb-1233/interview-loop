<script setup lang="ts">
import { computed } from 'vue'
import type { Evaluation } from '@/lib/types'

const props = defineProps<{ evaluation: Evaluation; pending: boolean; rescoring: boolean }>()
defineEmits<{ rescore: [] }>()
const labels = { logic: '内容与逻辑', relevance: '贴合问题', correctness: '信息完整', concision: '表达干净' }
const pending = computed(() => props.pending || props.evaluation.qualityStatus === 'PENDING_RESCORE')
const insufficient = computed(() => props.evaluation.qualityStatus === 'INSUFFICIENT_EVIDENCE')
const limited = computed(() => props.evaluation.qualityStatus === 'LIMITED_SAMPLE')
const review = computed(() => props.evaluation.qualityStatus === 'REVIEW_REQUIRED')
const missing = computed(() => (props.evaluation.missingEvidenceDimensions ?? []).map(key => labels[key]).join('、'))
</script>

<template>
  <section v-if="pending || insufficient || limited || review" class="quality-notice panel" role="status">
    <strong>{{ pending ? '转写已修改，等待重新评分' : review ? '评分与专业核查需要复核' : limited ? '本次作答较少，按已有回答总结' : '评分依据不完整' }}</strong>
    <p>{{ pending ? '当前分数对应修改前的回答，仅供参考；重新评分成功后会重新校验，符合条件才计入成长统计。' : review ? '专业核查与最高档评价存在待确认差异，当前分数仅供参考，暂不计入成长统计。可重新核对评分与原话依据。' : limited ? `本次已作答 ${evaluation.answeredRounds ?? 1} 轮，总结仅针对这些回答。样本有限，分数仅供参考，暂不计入成长比较。` : `缺少可核验的原话证据：${missing}。当前分数仅供参考，暂不计入成长统计及前后成绩比较。` }}</p>
    <button v-if="pending || insufficient || review" type="button" class="button secondary" :disabled="rescoring" @click="$emit('rescore')">{{ rescoring ? '重新评分中…' : pending ? '按修正后的回答重新评分' : review ? '重新核对评分' : '补充评分依据' }}</button>
  </section>
  <details v-if="evaluation.revisionHistory?.length" class="revisions panel">
    <summary>历史评分版本（{{ evaluation.revisionHistory.length }}） · 当前第 {{ evaluation.revision }} 版</summary>
    <article v-for="revision in evaluation.revisionHistory" :key="revision.revision">
      <strong>第 {{ revision.revision }} 版 · {{ revision.overallScore }} 分</strong>
      <time>{{ new Date(revision.createdAt).toLocaleString('zh-CN') }}</time>
      <p>{{ revision.summary }}</p>
      <p v-for="item in revision.evidence" :key="item.dimension">{{ labels[item.dimension] }} · 第 {{ item.roundNo }} 轮原话：{{ item.quote }}</p>
    </article>
  </details>
</template>

<style scoped>
.quality-notice,.revisions { padding:20px 24px;margin-bottom:24px; }
.quality-notice { border-left:3px solid var(--accent); }.quality-notice p,.revisions p { color:var(--text-2);line-height:1.8;font-size:14px; }
.revisions summary { cursor:pointer; }.revisions article { border-top:1px solid var(--border);margin-top:16px;padding-top:16px; }.revisions time { margin-left:16px;font-size:12px;color:var(--text-3); }
</style>
