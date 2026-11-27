<script setup lang="ts">
import { computed, onMounted, shallowRef, useTemplateRef } from 'vue'

import type { Scene } from '@/lib/types'
import { isFoundationScene } from '@/lib/sceneTaxonomy'

const props = defineProps<{
  scene: Scene
  mode: 'text' | 'voice' | 'video'
  busy: boolean
  error: string
}>()
const emit = defineEmits<{ confirm: [options: { file: File | null; jd: string; duration: number }]; cancel: [] }>()
const jd = shallowRef('')
const duration = shallowRef(10)
const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')
const selectedFile = shallowRef<File | null>(null)
const selectionError = shallowRef('')
const maxBytes = 2 * 1024 * 1024
const foundation = computed(() => isFoundationScene(props.scene.id))

onMounted(() => dialog.value?.showModal())

function chooseFile(event: Event): void {
  const file = (event.target as HTMLInputElement).files?.[0] ?? null
  selectionError.value = ''
  if (file && !file.name.toLowerCase().endsWith('.docx')) {
    selectionError.value = '请选择 .docx 格式的 Word 简历。'
    selectedFile.value = null
    return
  }
  if (file && file.size > maxBytes) {
    selectionError.value = '简历文件不能超过 2 MB。'
    selectedFile.value = null
    return
  }
  selectedFile.value = file
}

function clearFile(): void {
  selectedFile.value = null
  selectionError.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

function confirm(): void {
  if (!props.busy && !selectionError.value) emit('confirm', { file: selectedFile.value, jd: jd.value, duration: duration.value })
}

function cancel(event?: Event): void {
  if (props.busy) {
    event?.preventDefault()
    return
  }
  emit('cancel')
}
</script>

<template>
  <dialog ref="dialog" class="interview-dialog" aria-labelledby="start-title" @cancel="cancel" @close="cancel">
    <div class="dialog-body">
      <p class="eyebrow">{{ foundation ? '能力对练' : scene.category }}</p>
      <h2 id="start-title">开始{{ mode === 'video' ? '视频' : mode === 'voice' ? '语音' : '文字' }}{{ foundation ? '能力对练' : '面试' }}</h2>
      <p class="scene-name">{{ scene.title }} · {{ scene.position }}</p>
      <p v-if="foundation" class="description">{{ scene.goal }} 系统会通过连续追问观察你的实际表达，不需要上传简历。</p>
      <template v-else>
      <p class="description">可选上传 Word 简历，AI 面试官会结合当前面试阶段、岗位和简历内容提问。不上传则使用场景原有问题。</p>
      <label class="upload-label" for="resume-upload">上传简历（可选）</label>
      <input id="resume-upload" ref="fileInput" class="file-input" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" :disabled="busy" @change="chooseFile">
      <div v-if="selectedFile" class="file-summary"><span>{{ selectedFile.name }}</span><button type="button" :disabled="busy" @click="clearFile">移除</button></div>
      <p class="file-hint">仅支持文字版 .docx，最大 2 MB。原始文件不保存；提取文字会发送给已配置的大模型用于面试提问，也可在训练页清除。</p>
      </template>
      <label v-if="!foundation" class="upload-label">目标岗位 JD（可选）<textarea v-model="jd" class="field" rows="3" maxlength="4000" placeholder="粘贴至少 20 字的岗位职责与要求" /></label>
      <label v-if="mode !== 'text'" class="upload-label">本场时长<select v-model="duration" class="field"><option v-for="n in [5, 10, 15, 30, 60]" :key="n" :value="n">{{ n }} 分钟</option></select></label>
      <p v-if="selectionError || error" class="error-banner" role="alert">{{ selectionError || error }}</p>
      <div class="dialog-actions">
        <button class="button secondary" type="button" :disabled="busy" @click="cancel()">取消</button>
        <button class="button" type="button" :disabled="busy || !!selectionError" @click="confirm">{{ busy ? '正在准备场景…' : selectedFile ? '上传并开始' : '直接开始' }}</button>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.interview-dialog { width: min(540px, calc(100vw - 28px)); max-height: calc(100vh - 28px); padding: 0; border: 1px solid var(--line); border-radius:var(--radius-md); color: var(--ink); background:var(--card); box-shadow: 0 24px 80px rgba(16,37,43,.2); }
.interview-dialog::backdrop { background: rgba(8, 29, 34, .58); }
.dialog-body { padding: 28px; }
.dialog-body h2 { margin: 5px 0 8px; font: 700 29px/1.2 var(--font-ui); }
.scene-name { margin: 0 0 16px; color: var(--mint-dark); font-weight: 800; }
.description { margin: 0 0 22px; color: var(--ink-soft); font-size: 14px; line-height: 1.75; }
.upload-label { display: block; margin-bottom: 9px; font-size: 13px; font-weight: 800; }
.file-input { display: block; width: 100%; padding: 13px; border: 1px dashed var(--border-bright); border-radius:var(--radius); background: var(--bg-2); color: var(--ink); }
.file-summary { margin-top: 10px; display: flex; justify-content: space-between; gap: 12px; color: var(--ink); font-size: 13px; overflow-wrap: anywhere; }
.file-summary button { flex: none; border: 0; background: transparent; color: #9c3f33; cursor: pointer; }
.file-hint { margin: 12px 0 18px; color: var(--ink-soft); font-size: 12px; line-height: 1.6; }
.dialog-actions { margin-top: 25px; display: flex; justify-content: flex-end; gap: 10px; }
.interview-dialog { border-color:var(--border);background:var(--card);color:var(--text);box-shadow:0 30px 80px -20px rgba(15,23,42,.45);backdrop-filter:none;animation:dialog-in .2s ease both; }
.interview-dialog::backdrop { background:rgba(3,7,18,.76);backdrop-filter:none; }
.scene-name { color:var(--text-2); }
.file-input { border-color:var(--border);background:var(--bg-2);color:var(--text); }
.file-summary button { color:#cf9a92; }
@keyframes dialog-in { from { opacity:0;transform:scale(.94) translateY(12px); } to { opacity:1;transform:scale(1) translateY(0); } }
@media (prefers-reduced-motion:reduce) { .interview-dialog { animation:none; } }
</style>
