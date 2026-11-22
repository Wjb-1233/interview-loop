<script setup lang="ts">
import type { InterviewAssessment } from '@/lib/contracts/interviewAssessment'
defineProps<{ assessment: InterviewAssessment }>()
const statusLabels = { NOT_COVERED: '本场未考察', LIMITED: '证据有限', UNCERTAIN: '待确认', DEMONSTRATED: '已体现' }
const resultLabels = { INSUFFICIENT_SAMPLE: '作答样本不足', AWAITING_REVIEW: '结果待复核', INDEPENDENT_APPLICATION: '本次新题已体现独立应用', NEEDS_PRACTICE: '仍有要点需要练习' }
</script>

<template>
  <section v-if="assessment.transfer" class="assessment-panel panel transfer-result" aria-label="新题迁移结果">
    <p class="eyebrow">独立作答 · 新情境</p><h2>{{ resultLabels[assessment.transfer.result] }}</h2>
    <p>{{ assessment.transfer.note }}</p><p>已提交 {{ assessment.transfer.answeredRounds }} 轮 · 提示使用 {{ assessment.hintUses }} 次</p>
    <RouterLink :to="`/plans/${assessment.transfer.planId}`">返回训练计划 →</RouterLink>
  </section>
  <section v-if="assessment.professionalMatrix.length" class="assessment-panel panel" aria-label="岗位能力证据">
    <header><h2>岗位能力证据</h2><span>基于本场回答与考察要点整理</span></header>
    <p class="scope-note">结合原话核对已体现的能力、缺少的依据和待确认内容。</p>
    <div class="competency-grid">
      <article v-for="item in assessment.professionalMatrix" :key="item.competencyId" class="competency">
        <header><h3>{{ item.name }}</h3><span class="status" :class="item.status">{{ statusLabels[item.status] }}</span></header>
        <p>{{ item.reason }}</p>
        <blockquote v-for="evidence in item.evidence" :key="evidence.roundNo + evidence.quote">第 {{ evidence.roundNo }} 轮：“{{ evidence.quote }}”</blockquote>
        <p v-if="item.metPoints.length"><strong>已说明</strong> {{ item.metPoints.join('、') }}</p>
        <p v-if="item.status !== 'NOT_COVERED' && item.missingPoints.length"><strong>待补充</strong> {{ item.missingPoints.join('、') }}</p>
        <details><summary>查看考察要点</summary><ul><li v-for="point in item.expectedPoints" :key="point">{{ point }}</li></ul><small>{{ item.reviewed ? '管理员已核对要点' : '参考要点，尚未标记人工核对' }} · {{ item.rubricVersion }}</small></details>
      </article>
    </div>
  </section>
  <section v-if="assessment.evidenceTrace.length" class="assessment-panel panel" aria-label="面试追问依据">
    <header><h2>这次面试为什么这样追问</h2><span>查看问题对应的考察点和待补充依据</span></header>
    <ol class="trace-list"><li v-for="item in assessment.evidenceTrace" :key="item.roundNo">
      <p class="trace-label">第 {{ item.roundNo }} 轮 · {{ item.competency }}</p><p>{{ item.decisionReason }}</p>
      <blockquote v-for="observation in item.observations" :key="observation.point">{{ observation.point }}：“{{ observation.quote }}”</blockquote>
      <p class="next-question">下一问：{{ item.nextQuestion }}</p><small v-if="item.degraded">本轮证据观察暂不可用，已保留回答并使用保守追问。</small>
    </li></ol>
  </section>
</template>

<style scoped>
.assessment-panel { padding:26px 28px;margin:24px 0; }.assessment-panel h2 { margin:0;font-size:20px; }.assessment-panel header { display:flex;align-items:baseline;justify-content:space-between;gap:16px; }.assessment-panel header>span,.scope-note { color:var(--text-3);font-size:12px; }.assessment-panel p { line-height:1.8; }.competency-grid { display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px; }.competency { border:1px solid var(--border);border-radius:12px;padding:20px; }.competency h3 { margin:0;font-size:15px; }.competency p,.trace-list p { font-size:13px;color:var(--text-2); }.status { white-space:nowrap;font-size:11px;padding:4px 8px;background:var(--bg-2);border-radius:16px; }.status.DEMONSTRATED { color:var(--success); }.status.UNCERTAIN { color:var(--accent-strong); }blockquote { margin:12px 0;padding:8px 12px;border-left:2px solid var(--accent);font-size:12px;line-height:1.8;background:var(--bg-2); }details,small { font-size:11px;color:var(--text-3); }summary { cursor:pointer; }li { line-height:1.8; }.trace-list { list-style:none;padding:0;margin:16px 0 0; }.trace-list>li { padding:14px 0;border-top:1px solid var(--border); }.trace-label { font-weight:600; }.next-question { color:var(--accent-strong)!important; }.transfer-result a { color:var(--accent-strong);font-size:13px; }
</style>
