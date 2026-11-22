<script setup lang="ts">
import { onBeforeUnmount, onMounted, shallowRef, useTemplateRef } from 'vue'
import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { VRMLoaderPlugin, VRMUtils, type VRM, type VRMHumanBoneName } from '@pixiv/three-vrm'

const props = withDefaults(defineProps<{
  active?: boolean
  speaking?: boolean
  listening?: boolean
  label?: string
}>(), { active: false, speaking: false, listening: false, label: '虚拟面试官' })

const emit = defineEmits<{ ready: [value: boolean]; configured: [value: boolean] }>()

/** 随仓库提供的一次性模型文件，运行时不联网。 */
const MODEL_URL = '/avatars/vrm/sample.vrm'

/**
 * 取景参数（单位：米 / 度）。相机固定不动，靠头骨实际世界高度换算距离，
 * 换自己的 .vrm 不需要改数值：HEADROOM 是画面竖直可视高度，FOCUS_DROP 是视线焦点相对头骨的下沉量
 * （焦点落在脖子/锁骨，人物因此居中偏下，头顶留出呼吸空间）。
 */
const FRAME = {
  FOV: 22,
  HEADROOM: 0.68,
  FOCUS_DROP: 0.11,
  MIN_VISIBLE_WIDTH: 0.46,
  NEAR: 0.1,
  FAR: 20,
}

/**
 * 站姿：示例模型是 T-pose 绑骨，手臂平举会挡住整个画面。
 * 归一化骨骼的旋转轴与世界轴对齐（VRM1 正面朝 +Z），所以绕 Z 转即“把手臂放下来”，绕 Y 转是往身前收。
 */
const POSE = {
  ARM_DOWN: 1.26,       // 上臂下落约 72°
  ARM_FORWARD: 0.14,
  ELBOW: 0.26,
  WRIST: 0.1,
}

/** 动效参数（单位：秒 / 弧度 / 米）。数值都按“能看出来但不抢戏”标定。 */
const MOTION = {
  FPS: 30,
  MAX_DPR: 2,
  BREATH_SECONDS: 4.2,
  BREATH_LIFT: 0.004,      // 整体上下 ±4mm，峰峰 8mm（1cm 级）
  CHEST_BREATH: 0.012,     // 胸腔俯仰
  SWAY_SECONDS: 9.5,
  SWAY_YAW: 0.035,         // 头部左右微摆约 ±2°
  SWAY_PITCH: 0.012,
  BLINK_GAP_MIN: 3,
  BLINK_GAP_MAX: 7,
  BLINK_DURATION: 0.14,    // 闭 + 开总共 140ms
  LISTEN_TILT: 0.052,      // 倾听时头微侧 3°
  LISTEN_BLINK_SCALE: 1.35,
  NOD: 0.026,              // 说话点头约 ±1.5°
  AA_GAIN: 0.9,
  IH_GAIN: 0.35,
  OU_GAIN: 0.18,
  AUDIO_SMOOTH: 0.15,
  AUDIO_RELEASE: 0.07,
  AUDIO_RMS_FLOOR: 0.006,
  AUDIO_RMS_GAIN: 8,
}

const container = useTemplateRef<HTMLDivElement>('container')
const state = shallowRef<'loading' | 'ready' | 'error'>('loading')

let renderer: THREE.WebGLRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let vrm: VRM | null = null
let observer: ResizeObserver | null = null
let disposed = false
let opening: Promise<boolean> | null = null
let raf = 0
let last = 0
let acc = 0
let clock = 0
let blinkStart = -1
let nextBlink = 3 + Math.random() * 4
let fpsWindow = 0
let fpsFrames = 0

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

/** 真实音量：AvatarPresenter 转发的 TTS 播放音轨分析节点，与 PhotoPresenter / Live2D 同名同语义。 */
const audio = {
  analyser: null as AnalyserNode | null,
  bins: null as Float32Array | null,
  level: 0,
}

/** 逐帧快照，供验收读取实测口型权重与渲染帧率（仅开发构建挂到 window.__vrmDebug）。 */
const debug = { aa: 0, ih: 0, ou: 0, blink: 0, level: 0, fps: 0, mode: 'idle' as string }

function connect(): Promise<boolean> {
  if (disposed) return Promise.resolve(false)
  if (state.value === 'ready') return Promise.resolve(true)
  if (opening) return opening
  const task = boot()
  opening = task
  return task.finally(() => { if (opening === task) opening = null })
}

async function boot(): Promise<boolean> {
  if (disposed || !container.value) return false
  state.value = 'loading'
  try {
    if (!renderer) build()
    const next = await load()
    if (disposed) { VRMUtils.deepDispose(next.scene); return false }
    attach(next)
    state.value = 'ready'
    emit('ready', true)
    emit('configured', true)
    return true
  } catch (error) {
    console.error('[VrmPresenter] VRM 人物加载失败：', error)
    teardown()
    if (!disposed) {
      state.value = 'error'
      emit('ready', false)
      emit('configured', false)
    }
    return false
  }
}

function build(): void {
  const host = container.value
  if (!host) throw new Error('容器未就绪')
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' })
  renderer.setClearColor(0x000000, 0)
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.domElement.setAttribute('aria-hidden', 'true')
  host.appendChild(renderer.domElement)

  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(FRAME.FOV, 1, FRAME.NEAR, FRAME.FAR)
  const key = new THREE.DirectionalLight(0xfff2e2, 1.55)
  key.position.set(-1.1, 2.3, 1.9)
  const fill = new THREE.DirectionalLight(0xd9e6ff, 0.6)
  fill.position.set(1.7, 1.2, 1.5)
  const rim = new THREE.DirectionalLight(0xffffff, 1.1)
  rim.position.set(0.6, 1.9, -2.2)
  scene.add(key, fill, rim, new THREE.HemisphereLight(0xdfe9f0, 0x23282c, 0.75))

  resize()
  observer = new ResizeObserver(() => resize())
  observer.observe(host)
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('blur', onBlur)
  window.addEventListener('focus', onFocus)
}

function load(): Promise<VRM> {
  return new Promise((resolve, reject) => {
    const loader = new GLTFLoader()
    loader.register((parser) => new VRMLoaderPlugin(parser))
    loader.load(
      MODEL_URL,
      (gltf) => {
        const loaded = gltf.userData.vrm as VRM | undefined
        if (!loaded) { reject(new Error('VRM 解析结果缺少 userData.vrm')); return }
        resolve(loaded)
      },
      undefined,
      (error) => reject(error instanceof Error ? error : new Error(String(error))),
    )
  })
}

function attach(next: VRM): void {
  if (!scene || !camera) throw new Error('渲染器未就绪')
  vrm = next
  vrm.scene.traverse((object) => { object.frustumCulled = false })
  scene.add(vrm.scene)
  if (vrm.lookAt) vrm.lookAt.target = camera
  relaxArms(vrm)
  vrm.update(0)
  frameCamera()
  clock = 0
  blinkStart = -1
  nextBlink = MOTION.BLINK_GAP_MIN + Math.random() * (MOTION.BLINK_GAP_MAX - MOTION.BLINK_GAP_MIN)
  if (import.meta.env.DEV) (window as unknown as Record<string, unknown>).__vrmDebug = debug
  start()
}

function relaxArms(next: VRM): void {
  const bone = (name: VRMHumanBoneName): THREE.Object3D | null => next.humanoid.getNormalizedBoneNode(name)
  const left = bone('leftUpperArm')
  const right = bone('rightUpperArm')
  if (left) left.rotation.set(0, -POSE.ARM_FORWARD, -POSE.ARM_DOWN)
  if (right) right.rotation.set(0, POSE.ARM_FORWARD, POSE.ARM_DOWN)
  const leftElbow = bone('leftLowerArm')
  const rightElbow = bone('rightLowerArm')
  if (leftElbow) leftElbow.rotation.set(0, -POSE.ELBOW, 0)
  if (rightElbow) rightElbow.rotation.set(0, POSE.ELBOW, 0)
  const leftHand = bone('leftHand')
  const rightHand = bone('rightHand')
  if (leftHand) leftHand.rotation.set(0, -POSE.WRIST, 0)
  if (rightHand) rightHand.rotation.set(0, POSE.WRIST, 0)
}

/** 按头骨世界高度换算相机距离：默认头肩带胸口的特写，容器变窄时自动后退保证两肩不裁切。 */
function frameCamera(): void {
  if (!camera || !vrm) return
  const headNode = vrm.humanoid.getNormalizedBoneNode('head')
  const headY = headNode ? headNode.getWorldPosition(new THREE.Vector3()).y : 1.4
  const focusY = headY - FRAME.FOCUS_DROP
  const halfFov = (FRAME.FOV / 2) * (Math.PI / 180)
  const aspect = Math.max(0.35, camera.aspect)
  const byHeight = (FRAME.HEADROOM / 2) / Math.tan(halfFov)
  const byWidth = (FRAME.MIN_VISIBLE_WIDTH / 2) / (Math.tan(halfFov) * aspect)
  const distance = Math.max(byHeight, byWidth)
  camera.position.set(0, focusY, distance)
  camera.lookAt(0, focusY, 0)
  camera.updateProjectionMatrix()
}

function resize(): void {
  if (!renderer || !camera || !container.value) return
  const width = container.value.clientWidth || 1
  const height = container.value.clientHeight || 1
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MOTION.MAX_DPR))
  renderer.setSize(width, height, false)
  camera.aspect = width / height
  camera.updateProjectionMatrix()
  if (vrm) frameCamera()
}

function start(): void {
  if (raf || disposed) return
  last = performance.now()
  acc = 0
  raf = requestAnimationFrame(frame)
}

function stop(): void {
  if (raf) cancelAnimationFrame(raf)
  raf = 0
}

function onVisibility(): void { if (document.hidden) stop(); else start() }
function onBlur(): void { stop() }
function onFocus(): void { start() }

function frame(now: number): void {
  raf = requestAnimationFrame(frame)
  if (!renderer || !scene || !camera || !vrm) return
  const delta = (now - last) / 1000
  last = now
  if (delta <= 0 || delta > 0.25) return
  acc += delta
  if (acc < 1 / MOTION.FPS) return
  const step = acc
  acc = 0
  update(step)
  renderer.render(scene, camera)
}

function update(dt: number): void {
  if (!vrm) return
  clock += dt
  const t = clock
  const reduced = reduceMotion.matches
  const idle = props.active ? 1 : 0.6
  sampleAudio(dt)

  const open = props.speaking ? audio.level : 0
  debug.level = audio.level
  debug.mode = props.speaking ? 'speaking' : props.listening ? 'listening' : 'idle'

  const breath = reduced ? 0 : Math.sin((t / MOTION.BREATH_SECONDS) * Math.PI * 2)
  vrm.scene.position.y = breath * MOTION.BREATH_LIFT
  const chest = vrm.humanoid.getNormalizedBoneNode('chest')
  if (chest) chest.rotation.x = breath * MOTION.CHEST_BREATH

  const head = vrm.humanoid.getNormalizedBoneNode('head')
  if (head) {
    const sway = reduced ? 0 : Math.sin((t / MOTION.SWAY_SECONDS) * Math.PI * 2) * idle
    const tilt = !reduced && props.listening ? MOTION.LISTEN_TILT : 0
    const nod = !reduced && props.speaking ? Math.sin(t * 5.4) * MOTION.NOD * open : 0
    head.rotation.set(sway * MOTION.SWAY_PITCH + nod, sway * MOTION.SWAY_YAW, tilt)
  }

  const aa = open * MOTION.AA_GAIN
  const ih = open * MOTION.IH_GAIN
  // ou 叠加一点慢速起伏，避免三个元音同相出“一条曲线”的塑料感
  const ou = open * MOTION.OU_GAIN * (0.55 + 0.45 * Math.sin(t * 3.1))
  const expressions = vrm.expressionManager
  if (expressions) {
    expressions.setValue('aa', aa)
    expressions.setValue('ih', ih)
    expressions.setValue('ou', ou)
    expressions.setValue('blink', blinkValue(t))
  }
  debug.aa = aa
  debug.ih = ih
  debug.ou = ou

  fpsFrames += 1
  fpsWindow += dt
  if (fpsWindow >= 1) {
    debug.fps = Math.round(fpsFrames / fpsWindow)
    fpsFrames = 0
    fpsWindow = 0
  }

  vrm.update(dt)
}

/** 每 3–7 秒眨一次眼；倾听时频率略降。0 → 1 → 0 的 140ms 闭眼曲线。 */
function blinkValue(t: number): number {
  if (blinkStart < 0 && t >= nextBlink) blinkStart = t
  if (blinkStart < 0) { debug.blink = 0; return 0 }
  const progress = (t - blinkStart) / MOTION.BLINK_DURATION
  if (progress >= 1) {
    blinkStart = -1
    const gap = MOTION.BLINK_GAP_MIN + Math.random() * (MOTION.BLINK_GAP_MAX - MOTION.BLINK_GAP_MIN)
    nextBlink = t + (props.listening ? gap * MOTION.LISTEN_BLINK_SCALE : gap)
    debug.blink = 0
    return 0
  }
  const value = progress < 0.5 ? progress * 2 : (1 - progress) * 2
  debug.blink = value
  return value
}

/** 时域 RMS → 0..1，起音 0.15s、落音 0.07s 平滑；无音源时退回伪包络。与 PhotoPresenter 同一套标定。 */
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
  } else if (props.speaking) {
    target = envelope(clock)
  }
  const tau = target > audio.level ? MOTION.AUDIO_SMOOTH : MOTION.AUDIO_RELEASE
  audio.level += (target - audio.level) * (1 - Math.exp(-dt / tau))
}

/** 伪音量包络：有声但拿不到 AnalyserNode（例如重听走浏览器语音后备）时模拟音节起伏。 */
function envelope(t: number): number {
  const syllable = Math.sin(t * 11.3) * 0.5 + 0.5
  const word = Math.sin(t * 5.7 + 1.3) * 0.5 + 0.5
  const phrase = Math.sin(t * 2.1 + 0.7) * 0.5 + 0.5
  const value = 0.2 + 0.55 * syllable * (0.55 + 0.45 * word) + 0.25 * phrase
  return value > 1 ? 1 : value
}

function observeAudio(source: AnalyserNode | null): void {
  audio.analyser = source
  audio.bins = source ? new Float32Array(source.fftSize) : null
  if (!source) audio.level = 0
}

function finishAudio(): void { observeAudio(null) }
function disconnect(): void { finishAudio() }

function teardown(): void {
  stop()
  observer?.disconnect()
  observer = null
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('blur', onBlur)
  window.removeEventListener('focus', onFocus)
  if (vrm) {
    scene?.remove(vrm.scene)
    VRMUtils.deepDispose(vrm.scene)
    vrm = null
  }
  scene?.clear()
  audio.analyser = null
  audio.bins = null
  audio.level = 0
  if (renderer) {
    renderer.domElement.remove()
    renderer.dispose()
    renderer.forceContextLoss()
    renderer = null
  }
  scene = null
  camera = null
}

onMounted(() => { void connect() })
onBeforeUnmount(() => { disposed = true; teardown() })

defineExpose({ connect, disconnect, observeAudio, finishAudio, isConnected: () => state.value === 'ready' })
</script>

<template>
  <!-- 外层只做容器：语义挂在内部 role=img 上，避免与 AvatarPresenter 的 role=group 重复声明 -->
  <div class="vrm-presenter" :aria-hidden="true">
    <div ref="container" class="vrm-canvas" role="img" :aria-label="`${label} · VRM 3D`" />
    <span v-if="state === 'loading'" class="vrm-hint" role="status">正在准备 3D 人物…</span>
  </div>
</template>

<style scoped>
.vrm-presenter { position: absolute; inset: 0; overflow: hidden; background: radial-gradient(ellipse at 50% 30%, #565e64 0%, #3c4349 40%, #252a2e 76%, #1a1e21 100%); }
.vrm-canvas { position: absolute; inset: 0; }
.vrm-canvas :deep(canvas) { display: block; width: 100%; height: 100%; }
.vrm-hint { position: absolute; inset: 0; display: grid; place-items: center; color: #cfd8dd; font-size: 13px; }
</style>
