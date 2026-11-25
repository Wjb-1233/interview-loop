<script setup lang="ts">
import { avatarAssets } from '@/lib/avatarConfig'
import { onBeforeUnmount, onMounted, shallowRef, useTemplateRef } from 'vue'

const props = withDefaults(defineProps<{
  active?: boolean
  speaking?: boolean
  listening?: boolean
  label?: string
}>(), { active: false, speaking: false, listening: false, label: '讲师' })

const emit = defineEmits<{ 'photo-state': [value: 'loading' | 'ready' | 'error'] }>()

const DIR = '/avatars/presenter/'
const BASE = avatarAssets.photo
const SPEAKING = `${DIR}teacher-speaking.png`
const EYES = `${DIR}teacher-eyes-closed.png`

/**
 * 面部锚点表 —— 换照片只改这里。
 *
 * 坐标系：源照片的比例坐标（0..1，x 左→右，y 上→下），按 teacher.png 标定（1330×1773）。
 * 标定方法：把照片按原始尺寸打开，量出各锚点像素坐标，再除以照片宽高；也可用脚本扫描暗像素定位瞳孔/唇缝。
 *   - EYES.left / EYES.right：左右瞳孔中心 x；EYES.y：两眼连线高度
 *   - EYES.w / EYES.h：单眼遮罩外框；核心不透明区约为外框的 58%，其余是软边
 *   - EYES.skinShiftY：眼睑取色偏移（负值=整图上移，取眼睛下方的光滑皮肤填进眼睛遮罩；
 *     偏移量必须大于眼睛本身高度，否则遮罩里还会看到同一双眼睛）
 *   - BROW：双眉带外框；MOUTH：嘴部变形区外框；SEAM：唇缝暗部
 * COVER 必须与 .photo-frame 的 object-position 一致，否则遮罩整体偏移。
 * 换构图差异大的照片（侧脸/极近景）时：先改 IMAGE 与 COVER，再逐个锚点重标。
 */
const FACE = {
  IMAGE: { w: 1330, h: 1773 },
  COVER: { x: 0.5, y: 0.12 },
  EYES: { y: 0.248, left: 0.438, right: 0.5635, w: 0.104, h: 0.046, skinShiftY: -0.028 },
  BROW: { x: 0.5, y: 0.2135, w: 0.4, h: 0.042 },
  MOUTH: { x: 0.496, y: 0.357, w: 0.165, h: 0.07 },
  SEAM: { y: 0.3555, w: 0.125, h: 0.013 },
}

/** 动效参数表（时长单位秒，位移单位 px，角度单位 deg）。 */
const MOTION = {
  FRAME_MS: 1000 / 30,
  SPEAKING_BLEND: 0.15,
  BLINK_GAP: [3, 7] as const,
  BLINK_DURATION: 0.14,
  BLINK_CLOSE: 0.55,
  LID_ALPHA: 1,
  CREASE_ALPHA: 0.3,
  MOUTH_STRETCH: 0.075,
  SEAM_ALPHA: 0.62,
  BROW_LIFT: [1, 2] as const,
  NOD_DEG: 1.5,
  SWAY_DEG: 1,
  LISTEN_TILT_DEG: 1,
  GAZE_PX: 1,
  GAZE_GAP: [5, 11] as const,
  GAZE_HOLD: 0.5,
  BREATH: 1.6,
  SWAY_SECONDS: 4.8,
  AUDIO_SMOOTH: 0.15,       // 真实音量的平滑时间常数
  AUDIO_RMS_FLOOR: 0.006,   // 时域 RMS 的静音底噪（与 lib/live2d.ts 一致）
  AUDIO_RMS_GAIN: 8,        // RMS → 0..1 的增益
  AUDIO_RELEASE: 0.07,      // 释放（闭嘴）时间常数，短于起音，静音时不会啪一下闭死
}

const stage = useTemplateRef<HTMLDivElement>('stage')
const baseLayer = useTemplateRef<HTMLImageElement>('baseLayer')
const speakingLayer = useTemplateRef<HTMLImageElement>('speakingLayer')
const eyesLayer = useTemplateRef<HTMLImageElement>('eyesLayer')
const browImg = useTemplateRef<HTMLImageElement>('browImg')
const mouthImg = useTemplateRef<HTMLImageElement>('mouthImg')
const lipSeam = useTemplateRef<HTMLSpanElement>('lipSeam')
const lidPatch = useTemplateRef<HTMLDivElement>('lidPatch')
const lidImg = useTemplateRef<HTMLImageElement>('lidImg')
const lidCrease = useTemplateRef<HTMLSpanElement>('lidCrease')
const sheen = useTemplateRef<HTMLSpanElement>('sheen')

const state = shallowRef<'loading' | 'ready' | 'error'>('loading')
const sources = shallowRef<{ base: string; speaking: string; eyes: string }>({ base: BASE, speaking: SPEAKING, eyes: EYES })
const frames = shallowRef({ speaking: false, eyes: false })

let disposed = false
let raf = 0
let paused = true
let lastPaint = 0
let clock = 0
let speakingMix = 0
let blinkStart = -1
let nextBlink = 3 + Math.random() * 4
let gazeStart = -1
let gazeDir = 1
let nextGaze = 5 + Math.random() * 6
let reduced = false
let media: MediaQueryList | null = null
/** 真实音量：AvatarPresenter 转发的 TTS 播放音轨分析节点，与 Live2D 实例的 observeAudio 同名同语义。 */
const audio = {
  analyser: null as AnalyserNode | null,
  bins: null as Float32Array | null,
  level: 0,
}
let natural = { w: FACE.IMAGE.w, h: FACE.IMAGE.h }
let observer: ResizeObserver | null = null

function probe(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const image = new Image()
    image.decoding = 'async'
    image.onload = () => resolve(image.naturalWidth > 0)
    image.onerror = () => resolve(false)
    image.src = url
  })
}

function setVar(name: string, value: number): void {
  stage.value?.style.setProperty(name, `${value.toFixed(1)}px`)
}

/**
 * 把照片比例坐标换算成舞台像素坐标：与 object-fit: cover + object-position 同一套几何，
 * 遮罩与照片像素始终对齐，换容器尺寸/换照片尺寸都不需重标。
 */
function measure(): void {
  const element = stage.value
  if (!element) return
  const boxW = element.clientWidth || 1
  const boxH = element.clientHeight || 1
  const { w: imageW, h: imageH } = natural
  const scale = Math.max(boxW / imageW, boxH / imageH)
  const drawW = imageW * scale
  const drawH = imageH * scale
  const originX = (boxW - drawW) * FACE.COVER.x
  const originY = (boxH - drawH) * FACE.COVER.y
  const px = (fx: number): number => originX + fx * drawW
  const py = (fy: number): number => originY + fy * drawH
  const sx = (fw: number): number => fw * drawW
  const sy = (fh: number): number => fh * drawH

  setVar('--eye-lx', px(FACE.EYES.left))
  setVar('--eye-rx', px(FACE.EYES.right))
  setVar('--eye-y', py(FACE.EYES.y))
  setVar('--eye-w', sx(FACE.EYES.w))
  setVar('--eye-h', sy(FACE.EYES.h))
  setVar('--brow-x', px(FACE.BROW.x))
  setVar('--brow-y', py(FACE.BROW.y))
  setVar('--brow-w', sx(FACE.BROW.w))
  setVar('--brow-h', sy(FACE.BROW.h))
  setVar('--mouth-x', px(FACE.MOUTH.x))
  setVar('--mouth-y', py(FACE.MOUTH.y))
  setVar('--mouth-w', sx(FACE.MOUTH.w))
  setVar('--mouth-h', sy(FACE.MOUTH.h))
  setVar('--seam-x', px(FACE.MOUTH.x))
  setVar('--seam-y', py(FACE.SEAM.y))
  setVar('--seam-w', sx(FACE.SEAM.w))
  setVar('--seam-h', sy(FACE.SEAM.h))

  // 眼睑取色：整图向上平移，让眼睛下方的光滑皮肤落进眼睛遮罩
  if (lidImg.value) lidImg.value.style.transform = `translateY(${(FACE.EYES.skinShiftY * drawH).toFixed(1)}px)`
  if (lidCrease.value) lidCrease.value.style.top = `${(py(FACE.EYES.y) - sy(FACE.EYES.h) * 0.36).toFixed(1)}px`
  if (lipSeam.value) {
    lipSeam.value.style.left = `${(px(FACE.MOUTH.x) - sx(FACE.SEAM.w) / 2).toFixed(1)}px`
    lipSeam.value.style.top = `${(py(FACE.SEAM.y) - sy(FACE.SEAM.h) / 2).toFixed(1)}px`
    lipSeam.value.style.width = `${sx(FACE.SEAM.w).toFixed(1)}px`
    lipSeam.value.style.height = `${sy(FACE.SEAM.h).toFixed(1)}px`
  }
}

function observeAudio(source: AnalyserNode | null): void {
  audio.analyser = source
  audio.bins = source ? new Float32Array(source.fftSize) : null
  if (!source) audio.level = 0
}

/** 每帧采样真实音量：时域 RMS（取前 1/4 采样点，与 lib/live2d.ts 同一套做法）映射成 0..1，再做 0.15s 平滑。 */
function sampleAudio(dt: number): void {
  const analyser = audio.analyser
  let target = 0
  if (analyser && analyser.context.state === 'running') {
    const samples = audio.bins && audio.bins.length === analyser.fftSize
      ? audio.bins
      : (audio.bins = new Float32Array(analyser.fftSize))
    analyser.getFloatTimeDomainData(samples)
    const count = Math.max(1, Math.floor(samples.length * 0.25))
    let energy = 0
    for (let i = 0; i < count; i += 1) energy += samples[i] * samples[i]
    const rms = Math.sqrt(energy / count)
    target = Math.min(1, Math.max(0, (rms - MOTION.AUDIO_RMS_FLOOR) * MOTION.AUDIO_RMS_GAIN))
  }
  // 起音 0.15s 平滑，落音用更短的 0.07s，静音时嘴平滑合上而不是啪一下闭死
  const tau = target > audio.level ? MOTION.AUDIO_SMOOTH : MOTION.AUDIO_RELEASE
  audio.level += (target - audio.level) * (1 - Math.exp(-dt / tau))
}

/** 伪音量包络：完全没有音源（observeAudio(null)，例如课程视频无旁白）时模拟音节起伏。 */
function envelope(t: number): number {
  const syllable = Math.sin(t * 11.3) * 0.5 + 0.5
  const word = Math.sin(t * 5.7 + 1.3) * 0.5 + 0.5
  const phrase = Math.sin(t * 2.1 + 0.7) * 0.5 + 0.5
  const value = 0.2 + 0.55 * syllable * (0.55 + 0.45 * word) + 0.25 * phrase
  return value > 1 ? 1 : value
}

function blinkAmount(t: number): number {
  if (blinkStart < 0) return 0
  const progress = (t - blinkStart) / MOTION.BLINK_DURATION
  if (progress >= 1) return 0
  const phase = progress < MOTION.BLINK_CLOSE
    ? progress / MOTION.BLINK_CLOSE
    : (1 - progress) / (1 - MOTION.BLINK_CLOSE)
  return phase * phase * (3 - 2 * phase)
}

/** 偶发 0.5s 注视偏移：整图横向平移 1px。 */
function gazeShift(): number {
  if (gazeStart < 0) return 0
  const elapsed = clock - gazeStart
  if (elapsed > MOTION.GAZE_HOLD) return 0
  const fade = Math.min(1, Math.min(elapsed, MOTION.GAZE_HOLD - elapsed) / 0.08)
  return MOTION.GAZE_PX * gazeDir * fade
}

// 用户要求：3D 虚拟人做好之前，先用**静态照片**代表面试官，不做伪眨眼/伪口型
const STATIC_PORTRAIT = true

function paint(): void {
  const element = stage.value
  if (!element) return
  if (STATIC_PORTRAIT) {
    element.style.transform = 'translate3d(0, 0, 0) scale(1) rotate(0deg)'
    if (speakingLayer.value) speakingLayer.value.style.opacity = '0'
    if (eyesLayer.value) eyesLayer.value.style.opacity = '0'
    if (lidPatch.value) lidPatch.value.style.visibility = 'hidden'
    if (lidCrease.value) lidCrease.value.style.opacity = '0'
    if (mouthImg.value) mouthImg.value.style.visibility = 'hidden'
    if (lipSeam.value) lipSeam.value.style.opacity = '0'
    return
  }
  // 接了音轨就一律跟随实测电平（静音=闭嘴）；只有完全没有音源时才用伪包络
  const energy = audio.analyser ? audio.level : 0.55 + 0.45 * envelope(clock)
  const env = speakingMix * energy
  const blink = blinkAmount(clock)
  const breath = reduced ? 0 : Math.sin((clock / MOTION.BREATH) * 2 * Math.PI)
  const sway = reduced ? 0 : Math.sin((clock / MOTION.SWAY_SECONDS) * 2 * Math.PI)
  const nod = reduced ? 0 : Math.sin(clock * 2 * Math.PI * 1.7) * MOTION.NOD_DEG * speakingMix
  const tilt = sway * MOTION.SWAY_DEG * (1 - 0.35 * speakingMix) + nod
    + (props.listening && !props.speaking ? MOTION.LISTEN_TILT_DEG : 0)
  const gaze = reduced ? 0 : gazeShift()
  const scale = 1.02 + 0.006 * breath + 0.004 * speakingMix
  element.style.transform = `translate3d(${gaze.toFixed(2)}px, ${(0.9 * speakingMix).toFixed(3)}%, 0) scale(${scale.toFixed(4)}) rotate(${tilt.toFixed(3)}deg)`

  if (speakingLayer.value) speakingLayer.value.style.opacity = frames.value.speaking ? speakingMix.toFixed(3) : '0'
  if (eyesLayer.value) eyesLayer.value.style.opacity = frames.value.eyes ? blink.toFixed(3) : '0'

  // 静止时不合成整幅人脸副本（三张全尺寸图常驻合成会拉低帧率）
  if (lidPatch.value) {
    lidPatch.value.style.opacity = (blink * MOTION.LID_ALPHA).toFixed(3)
    lidPatch.value.style.visibility = blink > 0.002 ? 'visible' : 'hidden'
  }
  if (lidCrease.value) lidCrease.value.style.opacity = (blink * MOTION.CREASE_ALPHA).toFixed(3)

  if (mouthImg.value) {
    const stretch = reduced ? 0 : env * MOTION.MOUTH_STRETCH
    mouthImg.value.style.transform = `scaleY(${(1 + stretch).toFixed(4)})`
    mouthImg.value.style.visibility = !reduced && env > 0.004 ? 'visible' : 'hidden'
  }
  if (lipSeam.value) lipSeam.value.style.opacity = (reduced ? 0 : env * MOTION.SEAM_ALPHA).toFixed(3)
  if (browImg.value) {
    const lift = reduced
      ? 0
      : (MOTION.BROW_LIFT[0] + (MOTION.BROW_LIFT[1] - MOTION.BROW_LIFT[0]) * env) * speakingMix
    browImg.value.style.transform = `translateY(${(-lift).toFixed(2)}px)`
    browImg.value.style.visibility = lift > 0.01 ? 'visible' : 'hidden'
  }
  if (sheen.value) {
    const phase = (clock % 1.8) / 1.8
    sheen.value.style.opacity = reduced ? '0' : (0.24 * speakingMix).toFixed(3)
    sheen.value.style.transform = `translate3d(${(phase * 260 - 80).toFixed(1)}%, 0, 0) skewX(-12deg)`
  }
}

function scheduleBlink(): void {
  nextBlink = clock + MOTION.BLINK_GAP[0] + Math.random() * (MOTION.BLINK_GAP[1] - MOTION.BLINK_GAP[0])
}

function scheduleGaze(): void {
  nextGaze = clock + MOTION.GAZE_GAP[0] + Math.random() * (MOTION.GAZE_GAP[1] - MOTION.GAZE_GAP[0])
  gazeDir = Math.random() < 0.5 ? -1 : 1
}

function tick(now: number): void {
  raf = 0
  if (paused || disposed || state.value !== 'ready') return
  raf = requestAnimationFrame(tick)
  if (lastPaint && now - lastPaint < MOTION.FRAME_MS - 1) return
  const dt = lastPaint ? Math.min((now - lastPaint) / 1000, 0.12) : MOTION.FRAME_MS / 1000
  lastPaint = now
  clock += dt
  speakingMix += ((props.speaking ? 1 : 0) - speakingMix) * (1 - Math.exp(-dt / MOTION.SPEAKING_BLEND))
  sampleAudio(dt)
  if (blinkStart < 0 && clock >= nextBlink) blinkStart = clock
  if (blinkStart >= 0 && clock >= blinkStart + MOTION.BLINK_DURATION) {
    blinkStart = -1
    scheduleBlink()
  }
  if (!reduced) {
    if (gazeStart < 0 && clock >= nextGaze) gazeStart = clock
    if (gazeStart >= 0 && clock >= gazeStart + MOTION.GAZE_HOLD) {
      gazeStart = -1
      scheduleGaze()
    }
  }
  paint()
}

function start(): void {
  if (raf || disposed || state.value !== 'ready') return
  paused = false
  lastPaint = 0
  raf = requestAnimationFrame(tick)
}

function stop(): void {
  paused = true
  if (raf) cancelAnimationFrame(raf)
  raf = 0
}

function onVisibility(): void {
  if (document.hidden) stop()
  else start()
}

function onBlur(): void { stop() }

function onFocus(): void {
  if (!document.hidden) start()
}

function onReduced(): void {
  reduced = media ? media.matches : false
  if (!reduced) return
  gazeStart = -1
  if (mouthImg.value) mouthImg.value.style.transform = 'scaleY(1)'
  if (lipSeam.value) lipSeam.value.style.opacity = '0'
  if (browImg.value) browImg.value.style.transform = 'translateY(0px)'
}

function onBaseLoad(): void {
  const image = baseLayer.value
  if (image && image.naturalWidth > 0) natural = { w: image.naturalWidth, h: image.naturalHeight }
  measure()
  paint()
}

async function load(bust = 0): Promise<void> {
  const query = bust ? `?r=${bust}` : ''
  sources.value = { base: `${BASE}${query}`, speaking: `${SPEAKING}${query}`, eyes: `${EYES}${query}` }
  state.value = 'loading'
  emit('photo-state', 'loading')
  const base = await probe(`${BASE}${query}`)
  if (disposed) return
  if (!base) {
    state.value = 'error'
    emit('photo-state', 'error')
    return
  }
  const [speaking, eyes] = await Promise.all([
    probe(`${SPEAKING}${query}`),
    probe(`${EYES}${query}`),
  ])
  if (disposed) return
  frames.value = { speaking, eyes }
  state.value = 'ready'
  blinkStart = -1
  scheduleBlink()
  scheduleGaze()
  emit('photo-state', 'ready')
  measure()
  paint()
  if (!document.hidden) start()
}

function reload(): void {
  if (disposed) return
  stop()
  speakingMix = 0
  blinkStart = -1
  gazeStart = -1
  void load(Date.now())
}

onMounted(() => {
  media = window.matchMedia('(prefers-reduced-motion: reduce)')
  reduced = media.matches
  media.addEventListener('change', onReduced)
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('blur', onBlur)
  window.addEventListener('focus', onFocus)
  if (stage.value && typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => { measure(); paint() })
    observer.observe(stage.value)
  }
  void load()
})

onBeforeUnmount(() => {
  disposed = true
  stop()
  observer?.disconnect()
  observer = null
  media?.removeEventListener('change', onReduced)
  media = null
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('blur', onBlur)
  window.removeEventListener('focus', onFocus)
})

defineExpose({ observeAudio, reload, isReady: () => state.value === 'ready' })
</script>

<template>
  <div class="photo-presenter" :class="{ ready: state === 'ready', speaking, listening }" role="img" :aria-label="label">
    <div ref="stage" class="photo-stage" aria-hidden="true">
      <img v-if="state !== 'error'" ref="baseLayer" class="photo-frame" :src="sources.base" alt="" draggable="false" decoding="async" @load="onBaseLoad" />
      <img v-if="frames.speaking" ref="speakingLayer" class="photo-frame photo-overlay" :src="sources.speaking" alt="" draggable="false" decoding="async" />
      <img v-if="frames.eyes" ref="eyesLayer" class="photo-frame photo-overlay" :src="sources.eyes" alt="" draggable="false" decoding="async" />
      <div class="photo-face photo-brow" aria-hidden="true">
        <img ref="browImg" class="photo-frame photo-face-img" :src="sources.base" alt="" draggable="false" decoding="async" />
      </div>
      <div class="photo-face photo-mouth" aria-hidden="true">
        <img ref="mouthImg" class="photo-frame photo-face-img" :src="sources.base" alt="" draggable="false" decoding="async" />
        <span ref="lipSeam" class="photo-lip-seam" aria-hidden="true" />
      </div>
      <div ref="lidPatch" class="photo-face photo-lid" aria-hidden="true">
        <img ref="lidImg" class="photo-frame photo-face-img" :src="sources.base" alt="" draggable="false" decoding="async" />
        <span ref="lidCrease" class="photo-lid-crease" aria-hidden="true" />
      </div>
      <span ref="sheen" class="photo-sheen" aria-hidden="true" />
    </div>
    <span v-if="state === 'loading'" class="photo-placeholder" role="status">正在准备讲师…</span>
    <div v-if="state === 'error'" class="photo-error" role="status">
      <span>讲师照片加载失败</span>
      <button type="button" @click="reload">重新加载</button>
    </div>
  </div>
</template>

<style scoped>
.photo-presenter { position: relative; width: 100%; height: 100%; overflow: hidden; background: radial-gradient(ellipse at 50% 24%, #f6f3ec 0, #dedbd3 58%, #c7c4bc 100%); }
.photo-stage { position: absolute; inset: -4%; transform-origin: 50% 12%; will-change: transform; }
.photo-frame { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: 50% 12%; user-select: none; }
.photo-overlay { opacity: 0; will-change: opacity; }
.photo-face { position: absolute; inset: 0; pointer-events: none; -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat; }
.photo-face-img { will-change: transform; }
/* 眼睑取色来自眼睛下方皮肤，和眼周亮度略有差异，用一点点亮度/饱和补偿（换照片时可微调） */
.photo-lid .photo-face-img { filter: brightness(0.94) saturate(0.98); }
.photo-lid { opacity: 0; will-change: opacity; -webkit-mask-image: radial-gradient(ellipse at 50% 50%, #000 34%, #0000 100%), radial-gradient(ellipse at 50% 50%, #000 34%, #0000 100%); mask-image: radial-gradient(ellipse at 50% 50%, #000 34%, #0000 100%), radial-gradient(ellipse at 50% 50%, #000 34%, #0000 100%); -webkit-mask-size: var(--eye-w, 0px) var(--eye-h, 0px), var(--eye-w, 0px) var(--eye-h, 0px); mask-size: var(--eye-w, 0px) var(--eye-h, 0px), var(--eye-w, 0px) var(--eye-h, 0px); -webkit-mask-position: calc(var(--eye-lx, 0px) - var(--eye-w, 0px) / 2) calc(var(--eye-y, 0px) - var(--eye-h, 0px) / 2), calc(var(--eye-rx, 0px) - var(--eye-w, 0px) / 2) calc(var(--eye-y, 0px) - var(--eye-h, 0px) / 2); mask-position: calc(var(--eye-lx, 0px) - var(--eye-w, 0px) / 2) calc(var(--eye-y, 0px) - var(--eye-h, 0px) / 2), calc(var(--eye-rx, 0px) - var(--eye-w, 0px) / 2) calc(var(--eye-y, 0px) - var(--eye-h, 0px) / 2); }
.photo-lid-crease { position: absolute; left: calc(var(--eye-lx, 0px) - var(--eye-w, 0px) * 0.9); width: calc(var(--eye-rx, 0px) - var(--eye-lx, 0px) + var(--eye-w, 0px) * 1.8); height: 5px; opacity: 0; background: linear-gradient(180deg, #2b1a1470 0, #2b1a1400 100%); filter: blur(1.5px); }
.photo-mouth { -webkit-mask-image: radial-gradient(ellipse at 50% 50%, #000 60%, #0000 100%); mask-image: radial-gradient(ellipse at 50% 50%, #000 60%, #0000 100%); -webkit-mask-size: var(--mouth-w, 0px) var(--mouth-h, 0px); mask-size: var(--mouth-w, 0px) var(--mouth-h, 0px); -webkit-mask-position: calc(var(--mouth-x, 0px) - var(--mouth-w, 0px) / 2) calc(var(--mouth-y, 0px) - var(--mouth-h, 0px) / 2); mask-position: calc(var(--mouth-x, 0px) - var(--mouth-w, 0px) / 2) calc(var(--mouth-y, 0px) - var(--mouth-h, 0px) / 2); }
.photo-mouth .photo-face-img { transform-origin: var(--mouth-x, 50%) var(--mouth-y, 50%); }
.photo-lip-seam { position: absolute; border-radius: 50%; background: radial-gradient(ellipse at 50% 50%, #3b1e18d9 0, #3b1e1800 72%); opacity: 0; filter: blur(1px); }
.photo-brow { -webkit-mask-image: radial-gradient(ellipse at 50% 50%, #000 52%, #0000 100%); mask-image: radial-gradient(ellipse at 50% 50%, #000 52%, #0000 100%); -webkit-mask-size: var(--brow-w, 0px) var(--brow-h, 0px); mask-size: var(--brow-w, 0px) var(--brow-h, 0px); -webkit-mask-position: calc(var(--brow-x, 0px) - var(--brow-w, 0px) / 2) calc(var(--brow-y, 0px) - var(--brow-h, 0px) / 2); mask-position: calc(var(--brow-x, 0px) - var(--brow-w, 0px) / 2) calc(var(--brow-y, 0px) - var(--brow-h, 0px) / 2); }
.photo-sheen { position: absolute; inset: -10% -40%; background: linear-gradient(96deg, transparent 0%, #fffaf0b8 48%, transparent 100%); mix-blend-mode: screen; opacity: 0; pointer-events: none; will-change: transform, opacity; }
.photo-placeholder { position: absolute; inset: 0; display: grid; place-items: center; color: #4b5a5d; font-size: 13px; }
.photo-error { position: absolute; inset: auto 16px 16px; display: grid; justify-items: center; gap: 10px; padding: 12px; border-radius: 8px; background: #26323be6; color: #fff; font-size: 12px; }
.photo-error button { padding: 5px 10px; border: 1px solid #ffffff70; border-radius: 6px; background: transparent; color: #fff; cursor: pointer; }
</style>
