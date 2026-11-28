<script setup lang="ts">
import { markRaw, nextTick, onBeforeUnmount, onMounted, shallowRef, useTemplateRef, type Component } from 'vue'

/**
 * 在线数字人（Simli）是唯一形象来源：本地 3D / 照片 / Live2D 回退已下线。
 * 连不上时不再静默换形象，而是把具体失败原因上抛给房间直接显示，由用户决定重试。
 */
const loadSimliPresenter = () => import('@/components/media/SimliPresenter.vue')

type AvatarHandle = {
  connect: () => Promise<boolean>
  disconnect: () => void
  observeAudio: (source: AnalyserNode | null) => void
  finishAudio: () => void
  isConnected: () => boolean
  /** 数字人自己出声（Simli 回流带音轨）时为真，房间据此不再本地出声。 */
  ownsAudio?: () => boolean
  /** 最后一次失败的具体原因，用于原样显示给用户。 */
  lastError?: () => string
}

withDefaults(defineProps<{
  active?: boolean
  speaking?: boolean
  listening?: boolean
  label?: string
}>(), { active: false, speaking: false, listening: false, label: '虚拟面试官' })
const emit = defineEmits<{
  ready: [value: boolean]
  configured: [value: boolean]
  /** 数字人不可用：detail 是可直接展示的具体原因（含错误码 / HTTP 状态）。 */
  unavailable: [detail: string]
}>()

const simliComponent = shallowRef<Component | null>(null)
const simli = useTemplateRef<AvatarHandle>('simli')
const state = shallowRef<'loading' | 'ready' | 'error'>('loading')
const failure = shallowRef('')
const replayNotice = shallowRef('')
let replayNoticeTimer = 0
/** 组件是否已加载：用独立标记判断，避免把 simliComponent.value 收窄成 null。 */
let loaded = false
let disposed = false
let opening: Promise<boolean> | null = null

/** 重听退回浏览器朗读时的说明：口型拿不到音源，界面上要说清楚。 */
function noticeReplayFallback(message: string): void {
  replayNotice.value = message
  window.clearTimeout(replayNoticeTimer)
  replayNoticeTimer = window.setTimeout(() => { replayNotice.value = '' }, 8000)
}

function fail(detail: string): false {
  if (disposed) return false
  state.value = 'error'
  failure.value = detail
  emit('ready', false)
  emit('configured', false)
  emit('unavailable', detail)
  return false
}

async function boot(): Promise<boolean> {
  if (disposed) return false
  state.value = 'loading'
  failure.value = ''
  if (!loaded) {
    const module = await loadSimliPresenter()
    if (disposed) return false
    simliComponent.value = markRaw(module.default) as Component
    loaded = true
    await nextTick()
  }
  const handle = simli.value
  if (!handle) return fail('数字人组件未挂载，请刷新页面后重试')
  const ok = await handle.connect()
  return ok || fail(handle.lastError?.() || '数字人连接失败，原因未知')
}

function connect(): Promise<boolean> {
  if (disposed) return Promise.resolve(false)
  if (state.value === 'ready') return Promise.resolve(true)
  if (opening) return opening
  const task = boot()
  opening = task
  return task.finally(() => { if (opening === task) opening = null })
}

/** 重试要整个重建 Simli 组件：SDK 实例失败后不再复用。 */
function retry(): void {
  if (disposed || state.value === 'loading') return
  simliComponent.value = null
  loaded = false
  state.value = 'loading'
  failure.value = ''
  void nextTick(() => { void connect() })
}

function onSimliReady(value: boolean): void {
  if (!value || disposed) return
  state.value = 'ready'
  failure.value = ''
  emit('ready', true)
  emit('configured', true)
}

/** 会话中途掉线：保留具体原因，房间据此提示；不再换成别的形象。 */
function onSimliUnavailable(detail: string): void {
  if (disposed || state.value !== 'ready') return
  state.value = 'error'
  failure.value = detail
  emit('ready', false)
  emit('configured', false)
  emit('unavailable', detail)
}

/** 房间 TTS 播放音轨交给数字人做口型，接不上就是没有口型，但不影响语音面试。 */
function observeAudio(source: AnalyserNode | null): void {
  simli.value?.observeAudio(source)
}

function finishAudio(): void {
  simli.value?.finishAudio()
}

function disconnect(): void {
  simli.value?.disconnect()
}

/** 只有数字人真的在自己出声，房间才不该本地再播一遍。 */
function ownsAudio(): boolean {
  return state.value === 'ready' && (simli.value?.ownsAudio?.() ?? false)
}

onMounted(() => { void connect() })
onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(replayNoticeTimer)
  simli.value?.disconnect()
  emit('ready', false)
})

defineExpose({
  connect, disconnect, observeAudio, finishAudio, ownsAudio, retry, noticeReplayFallback,
  isConnected: () => state.value === 'ready',
  lastError: () => failure.value,
})
</script>

<template>
  <!-- 语义交给内部的数字人组件（role=group + 同一个 label），外层只做定位容器，避免同一名字出现两个可读组 -->
  <div class="avatar-presenter" :class="{ active, speaking, listening, connected: state === 'ready' }">
    <component
      :is="simliComponent"
      v-if="simliComponent"
      ref="simli"
      class="avatar-canvas"
      :active="active"
      :speaking="speaking"
      :listening="listening"
      :label="label"
      @ready="onSimliReady"
      @unavailable="onSimliUnavailable"
    />
    <span v-if="state === 'loading'" class="avatar-placeholder" role="status">正在接入在线数字人…</span>
    <div v-if="state === 'error'" class="avatar-error" role="alert">
      <span>数字人连接失败：{{ failure }}</span>
      <button type="button" @click="retry">重新连接数字人</button>
    </div>
    <span v-if="replayNotice" class="avatar-notice" role="status">{{ replayNotice }}</span>
    <span v-if="state === 'ready'" class="avatar-status">{{ speaking ? '正在讲解' : listening ? '认真倾听' : '准备就绪' }}</span>
    <span class="avatar-credit">在线数字人 · Simli</span>
  </div>
</template>

<style scoped>
.avatar-presenter { position: relative; width: 100%; height: 100%; overflow: hidden; background: radial-gradient(ellipse at 50% 30%, #fffaf0 0, #e7e6dc 55%, #d0dbd8 100%); }
/* 提示压在状态胶囊下方，不占房间右上角的计时器位置 */
.avatar-notice { position: absolute; top: 46px; left: 14px; padding: 4px 9px; border-radius: 6px; background: #26323bcc; color: #e8f0ee; font-size: 11px; }
.avatar-canvas { position: absolute; inset: 0; }
.avatar-canvas :deep(canvas) { display: block; width: 100%; height: 100%; }
.avatar-placeholder { position: absolute; inset: 0; display: grid; place-items: center; color: #4b5a5d; font-size: 13px; }
.avatar-status { position: absolute; top: 14px; left: 14px; padding: 5px 10px; border: 1px solid #ffffff70; border-radius: 20px; background: #f8fbf1cf; color: #40534d; font-size: 11px; white-space: nowrap; }
.avatar-error { position: absolute; inset: auto 16px 38px; display: grid; justify-items: center; gap: 10px; padding: 12px; border-radius: 8px; background: #26323be6; color: #fff; font-size: 12px; text-align: center; line-height: 1.6; }
.avatar-error button { padding: 5px 10px; border: 1px solid #ffffff70; border-radius: 6px; background: transparent; color: #fff; cursor: pointer; }
.avatar-credit { position: absolute; right: 10px; bottom: 8px; padding: 2px 5px; color: #41534c; background: #ffffffe0; border-radius: 4px; font-size: 10px; }
</style>
