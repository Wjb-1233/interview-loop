<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef } from 'vue'

const props = withDefaults(defineProps<{
  active?: boolean
  speaking?: boolean
  listening?: boolean
  label?: string
}>(), { active: false, speaking: false, listening: false, label: '微课老师' })
const emit = defineEmits<{ ready: [value: boolean]; configured: [value: boolean] }>()

// 主体素材：375×396 毛绒小熊（public/avatars/cartoon/bear.png）。
// 加载失败时回退到下方 SVG 兔子（保留原实现）。
const BEAR_SRC = '/avatars/cartoon/bear.png'
const failed = ref(false)

const TAU = Math.PI * 2
const VIEW_W = 200
const FRAME_MS = 1000 / 30          // 30fps 上限
const BLINK_MS = 140                // 一次眨眼（闭合+睁开）总时长
const BLINK_MIN_MS = 3000           // 3-7s 随机一次
const BLINK_SPAN_MS = 4000
const FLOAT_MS = 2600               // 待机浮动周期
const FLOAT_PX = 4                  // ±4px
const SWAY_MS = 5400                // 左右摇摆周期
const SWAY_DEG = 1                  // ±1°
const NOD_DEG = 2                   // 说话点头 ±2°
const LEAN_DEG = 2                  // 倾听前倾 2°
const TILT_DEG = 1.5                // 倾听歪头 1.5°
const EYE_GAIN = 1.03               // 倾听眼睛放大
const MOUTH_GAIN = 0.08             // 说话嘴部纵向缩放 1.0→1.08
const JUMP_PX = 2.2                 // 说话轻微上跳

const statusText = computed(() => (props.speaking ? '正在讲解' : props.listening ? '认真倾听' : '准备就绪'))

// ---- 标定：相对 375×396 原图宽高的比例（放大截图量取，见下方 CSS mask 同步）----
// 左眼盒 x127..164 / y118..155 → 中心 (145.5,136.5)
// 右眼盒 x211..252 / y131..163 → 中心 (231.5,147)
// 嘴盒   x170..204 / y164..184 → 中心 (187,174)

const host = useTemplateRef<HTMLDivElement>('host')
const bearBox = useTemplateRef<HTMLDivElement>('bearBox')
const bearHead = useTemplateRef<HTMLDivElement>('bearHead')
const lensEyeLeft = useTemplateRef<HTMLDivElement>('lensEyeLeft')
const lensEyeRight = useTemplateRef<HTMLDivElement>('lensEyeRight')
const mouthImg = useTemplateRef<HTMLImageElement>('mouthImg')
const lips = useTemplateRef<HTMLDivElement>('lips')
const lidLeft = useTemplateRef<HTMLElement>('lidLeft')
const lidRight = useTemplateRef<HTMLElement>('lidRight')

const pose = useTemplateRef<SVGGElement>('pose')
const head = useTemplateRef<SVGGElement>('head')
const tail = useTemplateRef<SVGGElement>('tail')
const earLeft = useTemplateRef<SVGGElement>('earLeft')
const earRight = useTemplateRef<SVGGElement>('earRight')
const browGroup = useTemplateRef<SVGGElement>('browGroup')
const eyeLeft = useTemplateRef<SVGGElement>('eyeLeft')
const eyeRight = useTemplateRef<SVGGElement>('eyeRight')
const mouth = useTemplateRef<SVGEllipseElement>('mouth')
const mouthLine = useTemplateRef<SVGPathElement>('mouthLine')
const tongue = useTemplateRef<SVGEllipseElement>('tongue')

let raf = 0
let lastStamp = 0
let clock = 0
let scale = 0.65
let focused = true
let reduced = false
let lean = 0
let eyeScale = 1
let earPerk = 0
let loud = 0
let mouthPx = 0
let blinkStart = -1
let nextBlinkAt = 3200
let analyser: AnalyserNode | null = null
let freqs: Uint8Array | null = null
let synthPhase = 0
let synthFreq = 7.2
let synthTimer = 0
let gate = 1
let gateUntil = 0
let quietMs = 0
let motionQuery: MediaQueryList | null = null
let observer: ResizeObserver | null = null

const num = (value: number): string => value.toFixed(2)
const setTransform = (element: Element | null, value: string): void => { element?.setAttribute('transform', value) }
const setStyle = (element: HTMLElement | null, value: string): void => { if (element) element.style.transform = value }

function measure(): void {
  const width = host.value?.clientWidth ?? 0
  scale = width > 8 ? width / VIEW_W : 0.65
}

// 说话包络：有真实音频时读频谱能量，没有时用 6-9Hz 随机包络模拟
function gateTick(): void {
  if (clock < gateUntil) return
  gate = Math.random() < 0.22 ? 0.15 : 1
  gateUntil = clock + 180 + Math.random() * 300
}

function synthStep(dt: number): number {
  synthTimer -= dt
  if (synthTimer <= 0) { synthTimer = 240 + Math.random() * 220; synthFreq = 6 + Math.random() * 3 }
  synthPhase = (synthPhase + (dt / 1000) * synthFreq) % 1
  return Math.pow(0.5 + 0.5 * Math.sin(synthPhase * TAU), 1.6)
}

// 静音超过 600ms（视频没旁白/被静音）就退化成模拟包络，避免嘴不动
function sampleEnvelope(dt: number): number {
  gateTick()
  const node = analyser
  if (node) {
    if (!freqs || freqs.length !== node.frequencyBinCount) freqs = new Uint8Array(node.frequencyBinCount)
    node.getByteFrequencyData(freqs)
    const bins = Math.min(freqs.length, 48)
    let sum = 0
    for (let index = 2; index < bins; index += 1) sum += freqs[index]
    const level = Math.min(1, (sum / Math.max(1, bins - 2) / 255) * 2.4)
    quietMs = level < 0.02 ? quietMs + dt : 0
    if (quietMs < 600) return level * gate
  }
  return synthStep(dt) * gate
}

function frame(stamp: number): void {
  raf = requestAnimationFrame(frame)
  if (!lastStamp) { lastStamp = stamp; return }
  const dt = stamp - lastStamp
  if (dt < FRAME_MS - 1.5) return
  lastStamp = stamp
  clock += Math.min(dt, 80)
  const time = clock / 1000

  // 眨眼：3-7s 随机一次，整次 140ms（reduced-motion 下也保留）
  if (blinkStart < 0 && clock >= nextBlinkAt) blinkStart = clock
  let lid = 1                                     // 1 全开，0 全闭
  if (blinkStart >= 0) {
    const progress = (clock - blinkStart) / BLINK_MS
    if (progress >= 1) { blinkStart = -1; nextBlinkAt = clock + BLINK_MIN_MS + Math.random() * BLINK_SPAN_MS }
    else if (progress < 0.32) lid = 1 - progress / 0.32
    else if (progress < 0.53) lid = 0
    else lid = (progress - 0.53) / 0.47
  }

  const speaking = props.speaking && !reduced
  const listening = props.listening && !reduced
  if (reduced) {
    lean = 0; eyeScale = 1; earPerk = 0
  } else {
    const leanTarget = listening ? LEAN_DEG : 0
    const eyeTarget = listening ? EYE_GAIN : 1
    const perkTarget = listening ? 1 : 0
    lean += (leanTarget - lean) * 0.1
    eyeScale += (eyeTarget - eyeScale) * 0.12
    earPerk += (perkTarget - earPerk) * 0.1
  }

  const target = speaking ? sampleEnvelope(dt) : 0
  loud += (target - loud) * (target > loud ? 0.55 : 0.3)
  const openPx = speaking ? 3 + 3 * loud : 0        // SVG 兔子开口 3-6px
  mouthPx += (openPx - mouthPx) * 0.5

  // ===== 小熊（主体）=====
  if (!failed.value) {
    const floatPx = reduced ? 0 : Math.sin((clock / FLOAT_MS) * TAU) * FLOAT_PX
    const sway = reduced ? 0 : Math.sin((clock / SWAY_MS) * TAU) * SWAY_DEG
    const jump = speaking ? -JUMP_PX * loud : 0
    setStyle(bearBox.value, `translateY(${num(floatPx + jump)}px) rotate(${num(sway + lean)}deg)`)

    const nod = speaking && !reduced ? Math.sin(time * TAU * 3.1) * NOD_DEG : 0
    setStyle(bearHead.value, `rotate(${num(nod + (listening ? TILT_DEG : 0))}deg)`)

    const eyeNow = `scale(${num(eyeScale)})`
    setStyle(lensEyeLeft.value, eyeNow)
    setStyle(lensEyeRight.value, eyeNow)

    setStyle(mouthImg.value, `scaleY(${num(reduced ? 1 : 1 + MOUTH_GAIN * loud)})`)
    const lipsOpen = reduced ? 0 : loud
    setStyle(lips.value, `scaleY(${num(1 + 0.3 * lipsOpen)})`)
    if (lips.value) lips.value.style.opacity = num(Math.min(1, lipsOpen * 0.9))

    const close = 1 - lid
    const lidY = `translateY(${num(-125 + 125 * close)}%)`
    setStyle(lidLeft.value, lidY)
    setStyle(lidRight.value, lidY)
    lidLeft.value?.style.setProperty('--lid', num(close))
    lidRight.value?.style.setProperty('--lid', num(close))
  }

  // ===== SVG 兔子（图片加载失败时的兜底）=====
  if (failed.value) {
    const breath = reduced ? 0 : (Math.sin((clock / FLOAT_MS) * TAU) * FLOAT_PX) / Math.max(0.2, scale)
    setTransform(pose.value, `translate(0 ${num(breath)}) rotate(${num(lean)} 100 252)`)
    const nod = speaking ? Math.sin(time * TAU * 3.1) * NOD_DEG : 0
    setTransform(head.value, `rotate(${num(nod + lean * 0.35)} 100 158)`)
    const sway = reduced ? 0 : Math.sin((clock / SWAY_MS) * TAU) * 3.2
    const swaySlow = reduced ? 0 : Math.sin((time * TAU) / 9.4 + 1.1) * 2.4
    const perk = earPerk * 7
    setTransform(earLeft.value, `rotate(${num(2 + perk + sway + swaySlow)} 72 52)`)
    setTransform(earRight.value, `rotate(${num(-2 - perk + sway - swaySlow)} 128 52)`)
    setTransform(tail.value, `rotate(${num(reduced ? 0 : Math.sin((time * TAU) / 8.6) * 7)} 58 200)`)
    const eyeX = `scale(${num(eyeScale)} ${num(eyeScale * lid)})`
    setTransform(eyeLeft.value, `translate(84 100) ${eyeX} translate(-84 -100)`)
    setTransform(eyeRight.value, `translate(116 100) ${eyeX} translate(-116 -100)`)
    setTransform(browGroup.value, `translate(0 ${num(reduced ? 0 : -2.6 * loud - 1.2 * earPerk)})`)
    const ry = Math.max(0.35, mouthPx / 2 / scale)
    const rx = 7 + (mouthPx * 0.1) / scale
    mouth.value?.setAttribute('ry', num(ry))
    mouth.value?.setAttribute('rx', num(rx))
    mouth.value?.setAttribute('cy', num(126 - ry * 0.5))
    tongue.value?.setAttribute('cy', num(126 - ry * 0.5 + ry * 0.42))
    tongue.value?.setAttribute('rx', num(rx * 0.58))
    tongue.value?.setAttribute('ry', num(Math.max(0, ry * 0.34)))
    tongue.value?.setAttribute('opacity', num(Math.max(0, Math.min(1, (mouthPx - 1.6) / 2))))
    mouthLine.value?.setAttribute('opacity', num(Math.max(0, Math.min(1, 1 - mouthPx / 2.2))))
  }
}

function start(): void {
  if (raf || document.visibilityState !== 'visible' || !focused) return
  lastStamp = 0
  raf = requestAnimationFrame(frame)
}

function stop(): void {
  if (raf) cancelAnimationFrame(raf)
  raf = 0
}

function sync(): void { if (document.visibilityState === 'visible' && focused) start(); else stop() }
function onBlur(): void { focused = false; sync() }
function onFocus(): void { focused = true; sync() }
function onMotionChange(): void { reduced = motionQuery?.matches ?? false }

function connect(): Promise<boolean> {
  start()
  return Promise.resolve(true)
}

function observeAudio(source: AnalyserNode | null): void {
  analyser = source
  freqs = null
}

function finishAudio(): void {
  analyser = null
  freqs = null
  quietMs = 0
  loud = 0
  mouthPx = 0
}

function disconnect(): void { finishAudio() }
function isConnected(): boolean { return true }

onMounted(() => {
  measure()
  observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
  if (observer && host.value) observer.observe(host.value)
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  reduced = motionQuery.matches
  motionQuery.addEventListener('change', onMotionChange)
  document.addEventListener('visibilitychange', sync)
  window.addEventListener('blur', onBlur)
  window.addEventListener('focus', onFocus)
  start()
  // 与 AvatarPresenter 保持一致：连接完成后异步回报，避免在挂载渲染过程中向上抛事件
  void nextTick(() => { emit('ready', true); emit('configured', true) })
})

onBeforeUnmount(() => {
  stop()
  observer?.disconnect()
  observer = null
  motionQuery?.removeEventListener('change', onMotionChange)
  document.removeEventListener('visibilitychange', sync)
  window.removeEventListener('blur', onBlur)
  window.removeEventListener('focus', onFocus)
  emit('ready', false)
})

defineExpose({ connect, disconnect, observeAudio, finishAudio, isConnected })
</script>

<template>
  <div ref="host" class="avatar-presenter cartoon-presenter" :class="{ active, speaking, listening, fallback: failed }" :aria-label="label" role="group">
    <template v-if="!failed">
      <div ref="bearBox" class="bear-box" aria-hidden="true">
        <img class="bear-img bear-base" :src="BEAR_SRC" alt="" draggable="false" @error="failed = true" />

        <!-- 头部：软边遮罩内单独旋转，实现点头 / 歪头 -->
        <div ref="bearHead" class="bear-head">
          <img class="bear-img" :src="BEAR_SRC" alt="" draggable="false" />

          <!-- 左右眼：遮罩内局部放大 1.03（倾听） -->
          <div ref="lensEyeLeft" class="lens lens-eye-left">
            <img class="bear-img" :src="BEAR_SRC" alt="" draggable="false" />
          </div>
          <div ref="lensEyeRight" class="lens lens-eye-right">
            <img class="bear-img" :src="BEAR_SRC" alt="" draggable="false" />
          </div>

          <!-- 嘴部：同一张图在遮罩内纵向缩放 1.0→1.08 + 唇缝暗部 -->
          <div class="lens lens-mouth">
            <img ref="mouthImg" class="bear-img" :src="BEAR_SRC" alt="" draggable="false" />
            <div ref="lips" class="lips"></div>
          </div>

          <!-- 眨眼：与毛色接近的软边遮罩，自上而下闭合 -->
          <span ref="lidLeft" class="lid lid-left"></span>
          <span ref="lidRight" class="lid lid-right"></span>
        </div>
      </div>
    </template>

    <svg v-else class="cartoon-stage" viewBox="0 0 200 267" role="img" :aria-label="`${label}：会动的卡通动物`">
      <defs>
        <radialGradient id="cartoon-fur" cx="45%" cy="28%" r="78%">
          <stop offset="0" stop-color="#F9E6CE" />
          <stop offset="1" stop-color="#E3BE97" />
        </radialGradient>
        <radialGradient id="cartoon-face" cx="42%" cy="26%" r="80%">
          <stop offset="0" stop-color="#FFF4E4" />
          <stop offset="1" stop-color="#EBC9A7" />
        </radialGradient>
        <radialGradient id="cartoon-ground" cx="50%" cy="50%" r="50%">
          <stop offset="0" stop-color="rgba(96,66,42,.26)" />
          <stop offset="1" stop-color="rgba(96,66,42,0)" />
        </radialGradient>
      </defs>

      <ellipse cx="100" cy="250" rx="56" ry="12" fill="url(#cartoon-ground)" />

      <g ref="pose" data-part="pose">
        <g ref="tail" data-part="tail">
          <circle cx="57" cy="228" r="11" fill="#F7E4CE" stroke="rgba(120,80,50,.2)" stroke-width="2" />
        </g>

        <ellipse cx="100" cy="208" rx="46" ry="55" fill="url(#cartoon-fur)" stroke="rgba(120,80,50,.2)" stroke-width="2" />
        <ellipse cx="100" cy="216" rx="29" ry="36" fill="#FFF8EE" opacity=".8" />
        <ellipse cx="60" cy="202" rx="13" ry="18" fill="url(#cartoon-fur)" stroke="rgba(120,80,50,.16)" stroke-width="1.6" transform="rotate(12 60 202)" />
        <ellipse cx="140" cy="202" rx="13" ry="18" fill="url(#cartoon-fur)" stroke="rgba(120,80,50,.16)" stroke-width="1.6" transform="rotate(-12 140 202)" />

        <rect x="66" y="146" width="68" height="14" rx="7" fill="var(--accent)" opacity=".92" />
        <circle cx="122" cy="153" r="7.5" fill="var(--accent)" />
        <path d="M124 157 q4 12 -1 18 q-5 -6 -4 -18 z" fill="var(--accent)" opacity=".86" />

        <g ref="head" data-part="head">
          <g ref="earLeft" data-part="ear-left">
            <ellipse cx="72" cy="34" rx="15" ry="27" fill="url(#cartoon-fur)" stroke="rgba(120,80,50,.2)" stroke-width="2" />
            <ellipse cx="72" cy="37" rx="7.5" ry="16" fill="#EFB3AB" opacity=".85" />
          </g>
          <g ref="earRight" data-part="ear-right">
            <ellipse cx="128" cy="34" rx="15" ry="27" fill="url(#cartoon-fur)" stroke="rgba(120,80,50,.2)" stroke-width="2" />
            <ellipse cx="128" cy="37" rx="7.5" ry="16" fill="#EFB3AB" opacity=".85" />
          </g>

          <circle cx="100" cy="96" r="56" fill="url(#cartoon-face)" stroke="rgba(120,80,50,.2)" stroke-width="2" />

          <ellipse cx="68" cy="114" rx="10" ry="6.5" fill="#EE9A92" opacity=".4" />
          <ellipse cx="132" cy="114" rx="10" ry="6.5" fill="#EE9A92" opacity=".4" />

          <ellipse cx="100" cy="118" rx="27" ry="19" fill="#FFFAF3" opacity=".92" />
          <ellipse cx="100" cy="112" rx="7" ry="5.2" fill="#6B4A33" />
          <ellipse cx="97.4" cy="110.4" rx="2" ry="1.5" fill="#fff" opacity=".55" />

          <ellipse ref="mouth" data-part="mouth" cx="100" cy="126" rx="7" ry="0.4" fill="#6B4A33" />
          <ellipse ref="tongue" cx="100" cy="127" rx="4" ry="1" fill="#E08C86" opacity="0" />
          <path ref="mouthLine" d="M92 124 q8 6 16 0" fill="none" stroke="#6B4A33" stroke-width="2.4" stroke-linecap="round" opacity="1" />

          <g ref="browGroup" data-part="brows">
            <path d="M73 87 Q80 82 87 86" fill="none" stroke="#6B4A33" stroke-width="3" stroke-linecap="round" opacity=".72" />
            <path d="M113 86 Q120 82 127 87" fill="none" stroke="#6B4A33" stroke-width="3" stroke-linecap="round" opacity=".72" />
          </g>

          <g ref="eyeLeft" data-part="eye-left">
            <ellipse cx="84" cy="100" rx="7.4" ry="8.2" fill="#3F312A" />
            <circle cx="81.6" cy="97.4" r="2.2" fill="#fff" opacity=".9" />
          </g>
          <g ref="eyeRight" data-part="eye-right">
            <ellipse cx="116" cy="100" rx="7.4" ry="8.2" fill="#3F312A" />
            <circle cx="113.6" cy="97.4" r="2.2" fill="#fff" opacity=".9" />
          </g>
        </g>
      </g>
    </svg>
    <span class="avatar-status">{{ statusText }}</span>
  </div>
</template>

<style scoped>
.cartoon-presenter { position: relative; width: 100%; height: 100%; overflow: hidden; background: #EEDEC9; }
.cartoon-presenter.fallback { background: radial-gradient(ellipse at 50% 24%, #FFFAF2 0, #F1E9DC 58%, #DED7CB 100%); }
.cartoon-stage { display: block; width: 100%; height: 100%; }

/* 图片盒与 375×396 原图等比，mask 百分比即原图比例 */
.bear-box { position: absolute; left: 0; right: 0; bottom: 0; width: 100%; aspect-ratio: 375 / 396; transform-origin: 50% 100%; will-change: transform; }
.bear-img { position: absolute; inset: 0; display: block; width: 100%; height: 100%; }
.bear-base {
  -webkit-mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0) 0, #000 6%);
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0) 0, #000 6%);
}
.bear-head {
  position: absolute; inset: 0; transform-origin: 50.7% 54.3%; will-change: transform;
  -webkit-mask-image: radial-gradient(ellipse 35% 25% at 50.7% 30.3%, #000 70%, rgba(0, 0, 0, 0) 100%);
  mask-image: radial-gradient(ellipse 35% 25% at 50.7% 30.3%, #000 70%, rgba(0, 0, 0, 0) 100%);
}

/* 左眼中心 (0.388, 0.3447)、右眼中心 (0.6173, 0.3712)：倾听时各放大 1.03 */
.lens { position: absolute; inset: 0; }
.lens-eye-left {
  transform-origin: 38.8% 34.47%;
  -webkit-mask-image: radial-gradient(ellipse 7.4% 7.2% at 38.8% 34.47%, #000 60%, rgba(0, 0, 0, 0) 100%);
  mask-image: radial-gradient(ellipse 7.4% 7.2% at 38.8% 34.47%, #000 60%, rgba(0, 0, 0, 0) 100%);
}
.lens-eye-right {
  transform-origin: 61.73% 37.12%;
  -webkit-mask-image: radial-gradient(ellipse 7.8% 6.8% at 61.73% 37.12%, #000 60%, rgba(0, 0, 0, 0) 100%);
  mask-image: radial-gradient(ellipse 7.8% 6.8% at 61.73% 37.12%, #000 60%, rgba(0, 0, 0, 0) 100%);
}

/* 嘴部中心 (0.4987, 0.4394)：遮罩内同一张图纵向缩放 1.0→1.08 + 唇缝暗部 */
.lens-mouth {
  -webkit-mask-image: radial-gradient(ellipse 5.2% 2.9% at 49.87% 43.94%, #000 76%, rgba(0, 0, 0, 0) 100%);
  mask-image: radial-gradient(ellipse 5.2% 2.9% at 49.87% 43.94%, #000 76%, rgba(0, 0, 0, 0) 100%);
}
.lens-mouth img { transform-origin: 49.87% 43.94%; }
.lips {
  position: absolute; left: 45.3%; top: 42.3%; width: 9.4%; height: 4%; border-radius: 50%;
  transform-origin: 50% 50%; opacity: 0; will-change: transform, opacity;
  background: radial-gradient(ellipse at 50% 46%, rgba(58, 16, 14, .92) 0, rgba(58, 16, 14, .7) 52%, rgba(58, 16, 14, 0) 84%);
}

/* 眼睑：与毛色接近的软边遮罩，闭合时自上而下盖住眼睛 */
.lid {
  position: absolute; border-radius: 50%; transform: translateY(-125%); will-change: transform;
  background: radial-gradient(ellipse 58% 54% at 50% 44%, #F1C98F 58%, rgba(241, 201, 143, 0) 100%);
}
.lid::after {
  content: ''; position: absolute; left: 14%; right: 14%; top: 44%; height: 26%; border-radius: 50%;
  background: radial-gradient(ellipse at 50% 50%, rgba(120, 78, 50, .5), rgba(120, 78, 50, 0) 76%);
  opacity: calc(var(--lid, 0) * .85);
}
.lid-left { left: 33.2%; top: 28.9%; width: 11.3%; height: 11.1%; }
.lid-right {
  left: 55.6%; top: 31.8%; width: 12.3%; height: 10.6%;
  background: radial-gradient(ellipse 58% 54% at 50% 44%, #E7B87F 58%, rgba(231, 184, 127, 0) 100%);
}

.avatar-status { position: absolute; top: 14px; left: 14px; padding: 5px 10px; border: 1px solid #ffffff70; border-radius: 20px; background: #f8fbf1cf; color: #40534d; font-size: 11px; white-space: nowrap; }
</style>
