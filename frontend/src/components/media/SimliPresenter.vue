<script setup lang="ts">
import { onBeforeUnmount, onMounted, shallowRef, useTemplateRef } from 'vue'
import type { SimliClient } from 'simli-client'
import { authorizedFetch } from '@/lib/api'

/**
 * 在线数字人面试官（Simli）。视频与声音是同一条 WebRTC 回流，画面比送进去的音频晚约 1 秒，
 * 所以回流带音轨时由这里的 <audio> 单独出声（ownsAudio），房间的本地 TTS 只送不播，
 * 嘴和声来自同一条流才不会错位；回退本地形象时 ownsAudio 为假，本地 TTS 照常出声。
 * 令牌由后端 /avatar/simli-session 现取现用（5 分钟有效，密钥不下发浏览器）。
 */
withDefaults(defineProps<{
  active?: boolean
  speaking?: boolean
  listening?: boolean
  label?: string
}>(), { active: false, speaking: false, listening: false, label: '虚拟面试官' })

const emit = defineEmits<{
  ready: [value: boolean]
  configured: [value: boolean]
  /** 连不上就交给 AvatarPresenter 回退本地形象，不弹错误阻塞面试。 */
  unavailable: [reason: string]
}>()

/** 8 秒还没出画就先给用户出口（继续等 / 切本地形象）；20 秒仍未出画才判失败，交给 AvatarPresenter 回退。 */
const SLOW_AFTER_S = 8
const TIMEOUT_MS = 20000

const videoEl = useTemplateRef<HTMLVideoElement>('video')
const audioEl = useTemplateRef<HTMLAudioElement>('audio')
const state = shallowRef<'loading' | 'ready' | 'error'>('loading')

let client: SimliClient | null = null
let tapped: AnalyserNode | null = null
let tap: MediaStreamAudioDestinationNode | null = null
let opening: Promise<boolean> | null = null
let disposed = false
/** 首帧约 7 秒：加载态按秒报数，超时就换文案并给出口，别让用户以为卡死。 */
const waited = shallowRef(0)
let clock = 0

function startClock(): void {
  window.clearInterval(clock)
  waited.value = 0
  clock = window.setInterval(() => { waited.value += 1 }, 1000)
}

function stopClock(): void {
  window.clearInterval(clock)
  clock = 0
}
/** 回流带音轨：由本组件出声。LiveKit 的 attach 会把 <audio> 的 muted 置回 false，
 *  所以没接管前必须一直静音，否则本地 TTS 与约 1 秒后的回流音会叠成两个声音。 */
let audioOwned = false
let adoptTimer = 0

function returnedTrack(): MediaStreamTrack | null {
  const stream = audioEl.value?.srcObject as MediaStream | null
  const tracks = stream?.getAudioTracks?.() ?? []
  return tracks[0] ?? null
}

function silenceReturnedAudio(): void {
  const el = audioEl.value
  if (!el) return
  audioOwned = false
  el.muted = true
}

/** 接管出声：确认回流真的有音轨，再解除静音。拿不到音轨就留给本地 TTS，避免整段无声。 */
function adoptReturnedAudio(): boolean {
  const el = audioEl.value
  if (!el || audioOwned) return audioOwned
  if (!returnedTrack()) return false
  audioOwned = true
  el.muted = false
  el.volume = 1
  void el.play().then(
    () => undefined,
    () => { audioOwned = false; el.muted = true },
  )
  window.clearInterval(adoptTimer)
  adoptTimer = 0
  return true
}

/** 音轨晚于建连到达：ready 后轮询几次，赶在第一句话之前接管。 */
function watchReturnedAudio(): void {
  window.clearInterval(adoptTimer)
  adoptTimer = window.setInterval(() => {
    if (disposed || state.value !== 'ready') { window.clearInterval(adoptTimer); adoptTimer = 0; return }
    if (adoptReturnedAudio()) { window.clearInterval(adoptTimer); adoptTimer = 0 }
  }, 250)
}

function withTimeout<T>(task: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error('timeout')), ms)
    task.then(
      (value) => { window.clearTimeout(timer); resolve(value) },
      (reason) => { window.clearTimeout(timer); reject(reason) },
    )
  })
}

async function fetchToken(): Promise<string> {
  const response = await withTimeout(authorizedFetch('/avatar/simli-session', { method: 'GET' }), TIMEOUT_MS)
  if (!response.ok) throw new Error(response.status === 503 ? 'not-configured' : 'unavailable')
  const body = await response.json() as { data?: { sessionToken?: string } }
  const token = body?.data?.sessionToken
  if (!token) throw new Error('unavailable')
  return token
}

/** 同一路音源再连一个 MediaStreamDestination：不出声，只供 SDK 转 PCM16 送口型。 */
function buildTap(): void {
  if (!client || !tapped || tap) return
  let destination: MediaStreamAudioDestinationNode
  try {
    // AnalyserNode.context 声明为 BaseAudioContext，这里拿到的是房间播放用的 AudioContext
    destination = (tapped.context as AudioContext).createMediaStreamDestination()
  } catch { return }
  const track = destination.stream.getAudioTracks()[0]
  if (!track) return
  try {
    client.listenToMediastreamTrack(track)
    tap = destination
  } catch { /* 推流通道开不起来：只保留无声视频 */ }
}

function attachTap(): void {
  if (!tapped || !tap) return
  try { tapped.connect(tap) } catch { /* 已连上 */ }
}

function detachTap(): void {
  if (!tapped || !tap) return
  try { tapped.disconnect(tap) } catch { /* 未连 */ }
}

function release(): void {
  window.clearInterval(adoptTimer)
  adoptTimer = 0
  stopClock()
  silenceReturnedAudio()
  detachTap()
  tap = null
  tapped = null
  const current = client
  client = null
  if (current) {
    try { void current.stop().catch(() => undefined) } catch { /* 会话已结束 */ }
  }
  videoEl.value?.pause()
  audioEl.value?.pause()
}

function fail(reason: unknown): boolean {
  if (disposed) return false
  release()
  state.value = 'error'
  emit('ready', false)
  emit('configured', false)
  emit('unavailable', typeof reason === 'string' ? reason : 'unavailable')
  return false
}

async function start(): Promise<boolean> {
  const video = videoEl.value
  const audio = audioEl.value
  if (!video || !audio) return fail('unavailable')
  state.value = 'loading'
  startClock()
  try {
    const token = await fetchToken()
    if (disposed) return false
    const { SimliClient, LogLevel } = await import('simli-client')
    if (disposed) return false
    const instance = new SimliClient(token, video, audio, null, LogLevel.ERROR)
    client = instance
    instance.on('error', (detail: string) => { if (client === instance) fail(detail) })
    instance.on('stop', () => { if (client === instance && !disposed) fail('closed') })
    await withTimeout(instance.start(), TIMEOUT_MS)
    if (disposed || client !== instance) return false
    stopClock()
    state.value = 'ready'
    emit('ready', true)
    emit('configured', true)
    buildTap()
    attachTap()
    // attach 解静音的回流音必须自己管：接管前一直静音，接管后才有声
    audioEl.value.muted = true
    adoptReturnedAudio()
    watchReturnedAudio()
    void video.play().catch(() => undefined)
    return true
  } catch (reason) {
    return fail(reason instanceof Error && reason.message !== 'timeout' ? 'unavailable' : reason)
  }
}

function connect(): Promise<boolean> {
  if (disposed) return Promise.resolve(false)
  if (state.value === 'ready') return Promise.resolve(true)
  if (opening) return opening
  const task = start()
  opening = task
  return task.finally(() => { if (opening === task) opening = null })
}

function disconnect(): void {
  release()
}

/** 与 PhotoPresenter/HumanPresenter 同名同语义：拿到房间 TTS 播放音轨的分析节点。 */
function observeAudio(source: AnalyserNode | null): void {
  if (source !== tapped) {
    detachTap()
    tapped = source
    tap = null
  }
  if (!source) return
  buildTap()
  attachTap()
}

/** 打断/重听：清空服务端缓冲，并立刻掐掉回流音，别让上一句的尾巴还在响。 */
function finishAudio(): void {
  detachTap()
  silenceReturnedAudio()
  try { client?.ClearBuffer() } catch { /* 会话已断开 */ }
}

/** 页面隐藏时停掉视频渲染与口型推流，回来再续上，避免后台白耗带宽与 CPU。 */
function onVisibility(): void {
  if (document.hidden) {
    detachTap()
    videoEl.value?.pause()
    audioEl.value?.pause()
    return
  }
  if (state.value !== 'ready') return
  void videoEl.value?.play().catch(() => undefined)
  if (adoptReturnedAudio()) void audioEl.value?.play().catch(() => undefined)
  attachTap()
}

onMounted(() => {
  document.addEventListener('visibilitychange', onVisibility)
  void connect()
})

onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('visibilitychange', onVisibility)
  release()
  emit('ready', false)
})

defineExpose({
  connect, disconnect, observeAudio, finishAudio,
  isConnected: () => state.value === 'ready',
  /** 回流音就是房间唯一声源时返回 true：本地 TTS 只送不播，避免两路声音差一秒。 */
  ownsAudio: () => adoptReturnedAudio(),
})
</script>

<template>
  <div class="simli-presenter interviewer-art" :class="{ active, speaking, listening, connected: state === 'ready' }" :aria-label="label" role="group">
    <video ref="video" class="simli-video" autoplay playsinline muted :aria-label="`${label} · 数字人视频`" />
    <audio ref="audio" class="simli-audio" autoplay muted playsinline />
    <Transition name="simli-fade">
      <div v-if="state === 'loading'" class="simli-loading" role="status" aria-live="polite">
        <svg class="simli-figure" viewBox="0 0 96 124" aria-hidden="true">
          <circle cx="48" cy="34" r="17" />
          <path d="M12 124c0-24 16-39 36-39s36 15 36 39z" />
        </svg>
        <p class="simli-loading-text">
          {{ waited >= SLOW_AFTER_S ? '数字人连接较慢，可继续等待或切换本地形象' : `正在接入数字人… 已等待 ${waited} 秒` }}
        </p>
        <button v-if="waited >= SLOW_AFTER_S" type="button" class="simli-switch" @click="fail('switched-to-local')">切换本地形象</button>
      </div>
    </Transition>
    <p v-if="state === 'error'" class="simli-loading-text simli-error">数字人不可用，已切换本地形象</p>
    <span v-if="state === 'ready'" class="simli-status">{{ speaking ? '正在讲解' : listening ? '认真倾听' : '准备就绪' }}</span>
  </div>
</template>

<style scoped>
.simli-presenter {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: radial-gradient(ellipse at center, #2a3742 0, #17212b 62%, #111a22 100%);
}
.simli-video {
  display: block;
  flex: none;
  width: auto;
  height: min(84%, 660px);
  max-width: calc(100% - 48px);
  object-fit: contain;
  border-radius: 12px;
  box-shadow: 0 12px 36px #0006;
  opacity: 0;
  transition: opacity 200ms ease-out;
}
.connected .simli-video { opacity: 1; }
.simli-audio { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.simli-loading { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 20px; padding: 24px; text-align: center; }
.simli-figure { width: 78px; height: 100px; fill: #7e9a93; animation: simli-breathe 2.6s ease-in-out infinite; }
.simli-loading-text { margin: 0; color: #b9c7c2; font-size: 13px; line-height: 1.7; }
.simli-switch { padding: 7px 16px; border: 1px solid #ffffff3d; border-radius: 18px; background: #f8fbf114; color: #e7efeb; font: inherit; font-size: 13px; cursor: pointer; transition: background 160ms ease, border-color 160ms ease; }
.simli-switch:hover { background: #f8fbf126; border-color: #ffffff66; }
.simli-switch:focus-visible { outline: 2px solid #9fd8c8; outline-offset: 2px; }
.simli-error { position: absolute; inset: 0; display: grid; place-items: center; }
.simli-fade-enter-active,
.simli-fade-leave-active { transition: opacity 200ms ease-out; }
.simli-fade-enter-from { opacity: 0; }
.simli-fade-leave-to { opacity: 0; }
@keyframes simli-breathe { 0%, 100% { opacity: .22; } 50% { opacity: .38; } }
@media (prefers-reduced-motion: reduce) { .simli-figure { animation: none; opacity: .3; } }
.simli-status { position: absolute; top: 14px; left: 14px; padding: 5px 10px; border: 1px solid #ffffff70; border-radius: 20px; background: #f8fbf1cf; color: #40534d; font-size: 11px; white-space: nowrap; }
</style>
