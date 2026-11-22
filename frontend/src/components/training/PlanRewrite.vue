<script setup lang="ts">
import { shallowRef } from 'vue'
import type { TrainingPlanTask } from '@/lib/types'
defineProps<{ task: TrainingPlanTask; suggestions: ReadonlyArray<{ roundNo: number; original: string; rewrite: string; problem: string }>; busy: boolean }>()
const emit = defineEmits<{ submit: [answer: string] }>()
const answer = shallowRef('')
</script>
<template>
  <section id="rewrite-task" class="panel rewrite">
    <h2>重答一题</h2>
    <p>选取一条原话，解决对应问题，保留真实事实。</p>
    <details v-for="item in suggestions" :key="item.roundNo"><summary>第 {{ item.roundNo }} 轮：{{ item.problem }}</summary><p>原话：{{ item.original }}</p><p>建议：{{ item.rewrite }}</p></details>
    <form @submit.prevent="emit('submit', answer)"><label>你的新回答<textarea v-model="answer" class="field" rows="5" minlength="10" maxlength="2000" required /></label><button class="button" :disabled="busy || answer.trim().length < 10">{{ busy ? '检查中…' : '提交改写并检查' }}</button></form>
    <p v-if="task.rewriteFeedback" role="status">{{ task.rewriteFeedback }}</p>
  </section>
</template>
<style scoped>.rewrite { padding: 22px; margin-top: 24px; }.rewrite form { display: grid; gap: 12px; }.rewrite details { margin: 12px 0; }</style>
