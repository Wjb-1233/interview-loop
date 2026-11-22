<script setup lang="ts">
import type { QuestionRubric } from '@/lib/contracts/interviewAssessment'
const props = defineProps<{ modelValue?: QuestionRubric | null; index: number }>()
const emit = defineEmits<{ 'update:modelValue': [value: QuestionRubric | null] }>()
function add(): void {
  emit('update:modelValue', { competency: '', version: 'v1', requiredPoints: [], acceptableVariants: [], commonMistakes: [], referenceUrl: null, reviewed: false, transferQuestions: [] })
}
function text(event: Event): string { return (event.target as HTMLInputElement).value }
function patch(key: keyof QuestionRubric, value: unknown): void {
  if (props.modelValue) emit('update:modelValue', { ...props.modelValue, [key]: value })
}
function lines(value: string): string[] { return value.split('\n').map(item => item.trim()).filter(Boolean) }
</script>
<template>
  <div class="rubric-editor">
    <button v-if="!modelValue" type="button" class="rubric-add" @click="add">+ 添加考察要点与迁移题</button>
    <details v-else open>
      <summary>第 {{ index + 1 }} 题考察标准</summary>
      <div class="rubric-fields">
        <label>岗位能力名称<input class="field" :value="modelValue.competency" maxlength="60" required @input="patch('competency', text($event))" /></label>
        <label>标准版本<input class="field" :value="modelValue.version" maxlength="40" required @input="patch('version', text($event))" /></label>
        <label>必需要点（每行一条，最多 8 条）<textarea class="field" rows="3" :value="modelValue.requiredPoints.join('\n')" @change="patch('requiredPoints', lines(text($event)))" /></label>
        <label>可接受的不同方案<textarea class="field" rows="2" :value="modelValue.acceptableVariants.join('\n')" @change="patch('acceptableVariants', lines(text($event)))" /></label>
        <label>典型误区<textarea class="field" rows="2" :value="modelValue.commonMistakes.join('\n')" @change="patch('commonMistakes', lines(text($event)))" /></label>
        <label>新题迁移（更换业务约束，每行一题，最多 4 题）<textarea class="field" rows="3" :value="modelValue.transferQuestions.join('\n')" @change="patch('transferQuestions', lines(text($event)))" /></label>
        <label>参考资料网址<input class="field" type="url" :value="modelValue.referenceUrl ?? ''" maxlength="500" @change="patch('referenceUrl', text($event).trim() || null)" /></label>
        <label class="rubric-check"><input type="checkbox" :checked="modelValue.reviewed" @change="patch('reviewed', ($event.target as HTMLInputElement).checked)" /> 已人工核对本题考察要点</label>
        <button type="button" class="rubric-remove" @click="emit('update:modelValue', null)">移除本题标准</button>
      </div>
    </details>
  </div>
</template>
<style scoped>
.rubric-editor { grid-column:2/-1; }.rubric-add,.rubric-remove { border:0;background:transparent;color:var(--accent-strong);padding:6px 0;font-size:12px;cursor:pointer; }.rubric-editor summary { cursor:pointer;font-size:12px;font-weight:600;padding:10px 0; }.rubric-fields { display:grid;gap:12px;padding:14px;border:1px solid var(--border);border-radius:10px; }.rubric-fields label { font-size:12px;color:var(--text-2);display:grid;gap:6px; }.rubric-fields .rubric-check { display:flex;align-items:center; }.rubric-fields .rubric-check input { width:auto; }
</style>
