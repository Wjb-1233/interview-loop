<script setup lang="ts">
import { markRaw, nextTick, onBeforeUnmount, onMounted, shallowRef, useTemplateRef, watch, type Component } from 'vue'
import type { LocalAvatar } from '@/lib/live2d'
import PhotoPresenter from '@/components/media/PhotoPresenter.vue'
import { avatarAssets, avatarOrder } from '@/lib/avatarConfig'

/**
 * VRM 3D 人物按需加载：three + three-vrm 只在这条分支确实被选中后才下载，
 * 回退到照片或 Live2D 的页面不承担这部分体积。先取模块再挂同步组件，ref 在 nextTick 后即可用。
 */
const loadVrmPresenter = () => import('@/components/media/VrmPresenter.vue')
const loadHumanPresenter = () => import('@/components/media/HumanPresenter.vue')
const loadSimliPresenter = () => import('@/components/media/SimliPresenter.vue')
type VrmHandle = {
  connect: () => Promise<boolean>
  disconnect: () => void
  observeAudio: (source: AnalyserNode | null) => void
  finishAudio: () => void
  isConnected: () => boolean
  /** 数字人自己出声（Simli 回流带音轨）时为真，房间据此不再本地出声。 */
  ownsAudio?: () => boolean
}

const props = withDefaults(defineProps<{
  active?: boolean
  speaking?: boolean
  listening?: boolean
  label?: string
}>(), { active: false, speaking: false, listening: false, label: '虚拟面试官' })
const emit = defineEmits<{ ready: [value: boolean]; configured: [value: boolean] }>()
const container = useTemplateRef<HTMLDivElement>('container')
const photo = useTemplateRef<InstanceType<typeof PhotoPresenter>>('photo')
const vrmComponent = shallowRef<Component | null>(null)
const vrm = useTemplateRef<VrmHandle>('vrm')
const humanComponent = shallowRef<Component | null>(null)
const human = useTemplateRef<VrmHandle>('human')
const simliComponent = shallowRef<Component | null>(null)
const simli = useTemplateRef<VrmHandle>('simli')
const state = shallowRef<'loading' | 'ready' | 'error'>('loading')
const mode = shallowRef<'probe' | 'simli' | 'human' | 'vrm' | 'photo' | 'live2d'>('probe')
const simliNotice = shallowRef('')
/** 重听退回浏览器朗读时的说明：口型拿不到音源，界面上要说清楚。 */
const replayNotice = shallowRef('')
let replayNoticeTimer = 0

function noticeReplayFallback(message: string): void {
  replayNotice.value = message
  window.clearTimeout(replayNoticeTimer)
  replayNoticeTimer = window.setTimeout(() => { replayNotice.value = '' }, 8000)
}
let avatar: LocalAvatar | null = null
let opening: Promise<boolean> | null = null
let disposed = false

let simliDisabled = false

/** VRM 模型探测：只发 HEAD，不下载整份模型就能决定走 3D 还是回退照片模式。 */
async function probeVrm(url: string): Promise<boolean> {
  try {
    const head = await fetch(url, { method: 'HEAD', cache: 'no-store' })
    if (head.ok) return true
    if (head.status !== 405) return false
    const ranged = await fetch(url, { headers: { Range: 'bytes=0-1023' }, cache: 'no-store' })
    return ranged.ok
  } catch { return false }
}

function probePhoto(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const image = new Image()
    image.onload = () => resolve(image.naturalWidth > 0)
    image.onerror = () => resolve(false)
    image.src = url
  })
}

function connect(): Promise<boolean> {
  if (disposed) return Promise.resolve(false)
  if (mode.value === 'simli') return simli.value?.connect() ?? Promise.resolve(true)
  if (mode.value === 'photo') return Promise.resolve(true)
  if (mode.value === 'human') return human.value?.connect() ?? Promise.resolve(true)
  if (mode.value === 'vrm') return vrm.value?.connect() ?? Promise.resolve(true)
  if (avatar) return Promise.resolve(true)
  if (opening) return opening
  const task = boot()
  opening = task
  return task.finally(() => { if (opening === task) opening = null })
}

async function bootVrm(): Promise<boolean> {
  const module = await loadVrmPresenter()
  if (disposed) return false
  vrmComponent.value = markRaw(module.default)
  mode.value = 'vrm'
  await nextTick()
  if (disposed || !vrm.value) return false
  const ok = await vrm.value.connect()
  if (!ok && !disposed) { mode.value = 'probe'; await nextTick() }
  return ok
}

async function bootSimli(): Promise<boolean> {
  const module = await loadSimliPresenter()
  if (disposed) return false
  simliComponent.value = markRaw(module.default)
  mode.value = 'simli'
  await nextTick()
  if (disposed || !simli.value) return false
  const ok = await simli.value.connect()
  if (!ok && !disposed) { mode.value = 'probe'; await nextTick() }
  return ok
}

async function bootHuman(): Promise<boolean> {
  const module = await loadHumanPresenter()
  if (disposed) return false
  humanComponent.value = markRaw(module.default)
  mode.value = 'human'
  await nextTick()
  if (disposed || !human.value) return false
  const ok = await human.value.connect()
  if (!ok && !disposed) { mode.value = 'probe'; await nextTick() }
  return ok
}

async function boot(): Promise<boolean> {
  if (disposed) return false
  mode.value = 'probe'
  state.value = 'loading'
  for (const provider of avatarOrder()) {
    if (disposed) return false
    try {
      if (provider === 'simli' && !simliDisabled) {
        if (await bootSimli()) return true
        simliNotice.value = '数字人不可用，已切换本地形象'
      }
      if (provider === 'human' && await probeVrm(avatarAssets.human) && await bootHuman()) return true
      if (provider === 'vrm' && await probeVrm(avatarAssets.vrm) && await bootVrm()) return true
      if (provider === 'photo' && await probePhoto(avatarAssets.photo)) {
        if (disposed) return false
        mode.value = 'photo'
        return true
      }
      if (provider === 'live2d') {
        if (disposed || !container.value) return false
        mode.value = 'live2d'
        return load()
      }
    } catch {
      // A missing dynamic chunk or WebGL failure must not prevent the next fallback.
      if (provider === 'simli') simliNotice.value = '数字人不可用，已切换本地形象'
      if (!disposed) { mode.value = 'probe'; await nextTick() }
    }
  }
  return false
}

async function load(): Promise<boolean> {
  if (disposed || !container.value) return false
  state.value = 'loading'
  try {
    const { createLocalAvatar } = await import('@/lib/live2d')
    if (disposed || !container.value) return false
    const next = await createLocalAvatar(container.value)
    if (disposed) { next.destroy(); return false }
    avatar = next
    next.setSpeaking(props.speaking)
    next.setListening(props.listening)
    next.setActive(props.active)
    state.value = 'ready'
    emit('ready', true); emit('configured', true)
    return true
  } catch {
    if (!disposed) { state.value = 'error'; emit('ready', false); emit('configured', false) }
    return false
  }
}

function onPhotoState(value: 'loading' | 'ready' | 'error'): void {
  state.value = value
  if (value === 'ready') { emit('ready', true); emit('configured', true) }
  else if (value === 'error') emit('ready', false)
}

function onVrmReady(value: boolean): void {
  if (!value) return
  state.value = 'ready'
  emit('ready', true)
  emit('configured', true)
}

const onHumanReady = onVrmReady
const onSimliReady = onVrmReady

/** 会话中途掉线：关掉数字人分支，用同一套回退顺序换成本地形象，面试继续。 */
function onSimliUnavailable(): void {
  if (disposed || mode.value !== 'simli') return
  simliDisabled = true
  simliNotice.value = '数字人不可用，已切换本地形象'
  void boot()
}

// 照片模式和 Live2D 模式都要吃到同一路播放音轨，口型才能跟真实音量走
function observeAudio(source: AnalyserNode | null): void {
  photo.value?.observeAudio(source)
  avatar?.observeAudio(source)
  human.value?.observeAudio(source)
  vrm.value?.observeAudio(source)
  simli.value?.observeAudio(source)
}
function finishAudio(): void {
  photo.value?.observeAudio(null)
  human.value?.finishAudio()
  vrm.value?.finishAudio()
  simli.value?.finishAudio()
  avatar?.observeAudio(null)
  avatar?.setSpeaking(false)
}
function disconnect(): void { finishAudio(); simli.value?.disconnect() }

/** 只有 Simli 分支会自己出声；回退本地形象后必须回到本地 TTS 出声，不能让房间一直静音。 */
function ownsAudio(): boolean {
  return mode.value === 'simli' && (simli.value?.ownsAudio?.() ?? false)
}
watch(() => props.speaking, (value) => avatar?.setSpeaking(value))
watch(() => props.listening, (value) => avatar?.setListening(value))
watch(() => props.active, (value) => avatar?.setActive(value))
onMounted(() => { void connect() })
onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(replayNoticeTimer)
  avatar?.destroy()
  avatar = null
  emit('ready', false)
})
defineExpose({ connect, disconnect, observeAudio, finishAudio, ownsAudio, noticeReplayFallback, isConnected: () => state.value === 'ready' })
</script>

<template>
  <div class="avatar-presenter interviewer-art" :class="{ active, speaking, listening, connected: state === 'ready', 'human-mode': mode === 'human' }" :aria-label="label" role="group">
    <PhotoPresenter
      v-if="mode === 'photo'"
      ref="photo"
      class="avatar-canvas"
      :active="active"
      :speaking="speaking"
      :listening="listening"
      :label="label"
      @photo-state="onPhotoState"
    />
    <component
      :is="simliComponent"
      v-else-if="mode === 'simli'"
      ref="simli"
      class="avatar-canvas"
      :active="active"
      :speaking="speaking"
      :listening="listening"
      :label="label"
      @ready="onSimliReady"
      @unavailable="onSimliUnavailable"
    />
    <component
      :is="humanComponent"
      v-else-if="mode === 'human'"
      ref="human"
      class="avatar-canvas"
      :active="active"
      :speaking="speaking"
      :listening="listening"
      :label="label"
      @ready="onHumanReady"
    />
    <component
      :is="vrmComponent"
      v-else-if="mode === 'vrm'"
      ref="vrm"
      class="avatar-canvas"
      :active="active"
      :speaking="speaking"
      :listening="listening"
      :label="label"
      @ready="onVrmReady"
    />
    <template v-else>
      <div ref="container" class="avatar-canvas" role="img" :aria-label="`${label} · Hiyori`" />
      <span v-if="state === 'loading'" class="avatar-placeholder" role="status">正在准备人物…</span>
    </template>
    <span v-if="replayNotice || simliNotice" class="avatar-notice" role="status">{{ replayNotice || simliNotice }}</span>
    <span v-if="state === 'ready'" class="avatar-status">{{ speaking ? '正在讲解' : listening ? '认真倾听' : '准备就绪' }}</span>
    <div v-if="state === 'error' && mode !== 'photo'" class="avatar-error" role="status">
      <span>人物加载失败，语音和课件仍可使用</span>
      <button type="button" @click="connect">重新加载人物</button>
    </div>
    <a v-if="mode === 'live2d'" class="avatar-credit" href="https://www.live2d.com/en/learn/sample/momose-hiyori/" target="_blank" rel="noopener noreferrer">Hiyori · © Live2D Inc.</a>
    <span v-else-if="mode === 'vrm'" class="avatar-credit">3D 虚拟人 · VRM</span>
    <span v-else-if="mode === 'human'" class="avatar-credit">写实 3D · Microsoft Rocketbox (MIT)</span>
    <span v-else-if="mode === 'simli'" class="avatar-credit">在线数字人 · Simli</span>
  </div>
</template>

<style scoped>
.avatar-presenter { position: relative; width: 100%; height: 100%; overflow: hidden; background: radial-gradient(ellipse at 50% 30%, #fffaf0 0, #e7e6dc 55%, #d0dbd8 100%); }
/* 写实 3D 分支用深色舞台，画布本身透明叠在舞台渐变上，不出现白底方块 */
.avatar-presenter.human-mode { background: radial-gradient(ellipse at 50% 26%, #2b333b 0, #1d242a 48%, #10151a 100%); }
/* 提示压在状态胶囊下方，不占房间右上角的计时器位置 */
.avatar-notice { position: absolute; top: 46px; left: 14px; padding: 4px 9px; border-radius: 6px; background: #26323bcc; color: #e8f0ee; font-size: 11px; }
.avatar-canvas { position: absolute; inset: 0; }
.avatar-canvas :deep(canvas) { display: block; width: 100%; height: 100%; }
.avatar-placeholder { position: absolute; inset: 0; display: grid; place-items: center; color: #4b5a5d; font-size: 13px; }
.avatar-status { position: absolute; top: 14px; left: 14px; padding: 5px 10px; border: 1px solid #ffffff70; border-radius: 20px; background: #f8fbf1cf; color: #40534d; font-size: 11px; white-space: nowrap; }
.avatar-error { position: absolute; inset: auto 16px 38px; display: grid; justify-items: center; gap: 10px; padding: 12px; border-radius: 8px; background: #26323be6; color: #fff; font-size: 12px; }
.avatar-error button { padding: 5px 10px; border: 1px solid #ffffff70; border-radius: 6px; background: transparent; color: #fff; cursor: pointer; }
/* 写实 3D 的署名由 HumanPresenter 自己渲染（带具体模型名、悬停在右上角），避免右下角两份叠着 */
.avatar-presenter.human-mode .avatar-credit { display: none; }
.avatar-credit { position: absolute; right: 10px; bottom: 8px; padding: 2px 5px; color: #41534c; background: #ffffffe0; border-radius: 4px; font-size: 10px; text-decoration: none; }
.avatar-credit:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
