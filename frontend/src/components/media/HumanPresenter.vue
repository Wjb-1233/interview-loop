<script setup lang="ts">
import { avatarAssets } from '@/lib/avatarConfig'
import { onBeforeUnmount, shallowRef, useTemplateRef } from 'vue'
import * as THREE from 'three'
import { FBXLoader } from 'three/addons/loaders/FBXLoader.js'

const props = withDefaults(defineProps<{
  active?: boolean
  speaking?: boolean
  listening?: boolean
  label?: string
}>(), { active: false, speaking: false, listening: false, label: '虚拟面试官' })

const emit = defineEmits<{ ready: [value: boolean]; configured: [value: boolean] }>()

/**
 * 写实向 3D 面试官：Microsoft Rocketbox（MIT）Business Male 01。
 * 素材随仓库提供，运行时不联网；身体 fbx 绑骨（Bip01 / 3ds Max Biped），面部 fbx 单独带 blendshape。
 */
const MODEL = {
  DIR: '/avatars/human/',
  BODY: avatarAssets.human,
  FACE: avatarAssets.humanFace,
}

/** FBX 内部引用的是 3ds Max 的绝对 .tga 路径，这里按文件名改到随仓库的 webp 上，避免 404 与 12MB TGA。 */
const TEXTURES: Record<string, string> = {
  m005_body_color: 'm005_body_color.webp',
  m005_body_normal: 'm005_body_normal.webp',
  m005_body_specular: 'm005_body_specular.webp',
  m005_head_color: 'm005_head_color.webp',
  m005_head_normal: 'm005_head_normal.webp',
  m005_head_specular: 'm005_head_specular.webp',
  m005_opacity_color: 'm005_opacity_color.webp',
}
/** 贴图缺失时的 1×1 透明像素，让 FBXLoader 拿到合法图片而不是报错重试。 */
const BLANK = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=='

/**
 * 取景参数（单位：米 / 度）。相机固定，只用容器宽高比换算距离与 fov：
 * 竖直可视区 VISIBLE_HEIGHT 覆盖“头顶下方一点 → 胸口以下”，HEAD_PAD 是头顶留白（占可视高度的 8%），
 * 左右肩要完整，所以横向至少看清 VISIBLE_WIDTH（含自然下垂的手臂），窄容器靠加大 fov + 拉远补足。
 */
const FRAME = {
  FOV_BASE: 26,
  FOV_MAX: 34,
  FOV_SLOPE: 22,
  NARROW_ASPECT: 1.15,
  VISIBLE_HEIGHT: 0.62,
  VISIBLE_WIDTH: 0.72,
  HEAD_PAD: 0.05,
  NEAR: 0.1,
  FAR: 40,
  STAND_HEIGHT: 1.7,
}

/** 站姿：Rocketbox 导出是 T-pose，上臂要压到身体两侧，肘部再收一点，否则半身像里会被画框切成两条横杠。 */
const POSE = {
  ARM_OUT: 0.16,
  ARM_FORWARD: 0.05,
  ELBOW: 0.14,
}

/** 动效参数（秒 / 弧度）。数值按“看得到但不起眼”标定。 */
const MOTION = {
  FPS: 30,
  MAX_DPR: 2,
  BREATH_SECONDS: 4.4,
  BREATH_LIFT: 0.0035,
  CHEST_BREATH: 0.028,
  SHOULDER_BREATH: 0.016,
  SWAY_SECONDS: 9.5,
  SWAY_YAW: 0.022,
  SWAY_PITCH: 0.008,
  BLINK_GAP_MIN: 3,
  BLINK_GAP_MAX: 7,
  BLINK_DURATION: 0.16,
  LISTEN_TILT: 0.052,
  LISTEN_BLINK_SCALE: 1.35,
  NOD: 0.03,
  JAW_GAIN: 0.85,
  AUDIO_SMOOTH: 0.15,
  AUDIO_RELEASE: 0.07,
  AUDIO_RMS_FLOOR: 0.006,
  AUDIO_RMS_GAIN: 8,
}

/** 曝光：ACES 之后皮肤要“有亮度但不发白”，1.02 是实测不过曝的上限附近。 */
const TONE = { EXPOSURE: 1.02 }

/**
 * 领带染色（只改贴图，不动几何）。m005_body_color 里领带正好落在 UV 图集右下方这一块，
 * 手/其他皮肤的 UV 在左右下角，所以先用矩形圈住领带岛，再按“高饱和红”逐像素压成深酒红。
 */
const TIE = {
  X0: 0.34, X1: 0.66, Y0: 0.80, Y1: 1,
  RED: 80, RATIO_G: 1.5, RATIO_B: 1.35, SAT: 0.45,
  MIX: 0.9, WINE: { R: 0.66, G: 0.12, B: 0.26 },
}

/**
 * 眼睛高光点：世界尺度（米）。OFFSET 要大于眼球半径（约 12mm），否则高光点落在眼球内部被自己挡掉；
 * SIZE 控制在瞳孔量级，再大就成卡通大眼了。
 */
const GLINT = { OFFSET: 0.016, SIZE: 0.0055, OPACITY: 0.45 }

const container = useTemplateRef<HTMLDivElement>('container')
const state = shallowRef<'loading' | 'ready' | 'error'>('loading')

let renderer: THREE.WebGLRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let root: THREE.Group | null = null
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
let topY = FRAME.STAND_HEIGHT
let baseY = 0

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

/** 需要逐帧摆动的骨骼：保存静止姿态四元数，每帧在它上面叠加增量，避免误差累积。 */
type BoneRig = { bone: THREE.Object3D; rest: THREE.Quaternion }
const rig = {
  spine: [] as BoneRig[],
  shoulders: [] as BoneRig[],
  neck: [] as BoneRig[],
  head: [] as BoneRig[],
}
const jawBones: { bone: THREE.Object3D; rest: THREE.Quaternion; sign: number }[] = []

/** 面部 morph：名称 → (mesh, 下标)。眨眼与说话都走这里；没有 morph 时两者都不伪造。 */
type Morph = { mesh: THREE.Mesh; index: number }
const morphs = { blinkLeft: [] as Morph[], blinkRight: [] as Morph[], blinkAll: [] as Morph[], jaw: [] as Morph[] }

const audio = { analyser: null as AnalyserNode | null, bins: null as Float32Array | null, level: 0 }

/** 眼里的那点高光：贴在眼球前方的小 sprite，逐帧跟着相机走位，靠它消掉“死眼”。 */
const glints: { sprite: THREE.Sprite; bone: THREE.Object3D }[] = []
let glintTexture: THREE.Texture | null = null
const glintA = new THREE.Vector3()
const glintB = new THREE.Vector3()

/** 逐帧快照，供验收读取实测口型权重与帧率（仅开发构建挂到 window.__humanDebug）。 */
const debug = {
  fps: 0,
  level: 0,
  blink: 0,
  jaw: 0,
  mode: 'idle' as string,
  morphKeys: [] as string[],
  blinkKeys: [] as string[],
  jawKeys: [] as string[],
  frame: { fov: 0, distance: 0, aspect: 1, top: 0, bottom: 0 },
  meshes: [] as string[],
  materials: [] as string[],
  tint: 'pending' as string,
  bones: [] as string[],
  bezel: { headTop: 1, shoulder: 1 },
  pause: false,
  override: { speaking: null as boolean | null, listening: null as boolean | null, level: null as number | null, blink: null as number | null },
}

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
    const [body, face] = await Promise.all([loadModel(MODEL.BODY), loadModel(MODEL.FACE)])
    if (disposed) { disposeTree(body); disposeTree(face); return false }
    assemble(body, face)
    state.value = 'ready'
    emit('ready', true)
    emit('configured', true)
    if (!document.hidden) start()
    return true
  } catch (error) {
    console.error('[HumanPresenter] 写实人物加载失败：', error)
    teardown()
    if (!disposed) { state.value = 'error'; emit('ready', false); emit('configured', false) }
    return false
  }
}

function build(): void {
  const host = container.value
  if (!host) throw new Error('容器未就绪')
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' })
  renderer.setClearColor(0x000000, 0)
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  // 1.02：ACES 压高光后皮肤刚好不过曝；再高额头和鼻梁就糊成一片白
  renderer.toneMappingExposure = TONE.EXPOSURE
  renderer.domElement.setAttribute('aria-hidden', 'true')
  host.appendChild(renderer.domElement)

  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(FRAME.FOV_BASE, 1, FRAME.NEAR, FRAME.FAR)
  scene.environment = buildEnvironment(renderer)
  scene.add(...buildLights())
  resize()
  observer = new ResizeObserver(() => { resize(); start() })
  observer.observe(host)
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('blur', onBlur)
  window.addEventListener('focus', onFocus)
}

/**
 * 柔和三点光 + 弱环境光：主光 45° 上前方、补光在另一侧压暗部、轮廓光从后上方勾脸颊和肩线。
 * 配比按“头肩要立体”调：主光/环境撑亮度，补光只留一丝冷色勾边，轮廓光偏暖压在后颈与肩线上；
 * 正面平光是“面片感”的来源，所以补光砍到主光的 1/6 左右，暗部交给环境贴图慢慢过渡。
 */
function buildLights(): THREE.Light[] {
  const key = new THREE.DirectionalLight(0xfff2e2, 2.9)
  key.position.set(-1.0, 2.4, 1.7)
  const fill = new THREE.DirectionalLight(0xcfdcee, 0.42)
  fill.position.set(2.0, 1.2, 1.1)
  const rim = new THREE.DirectionalLight(0xffd9b4, 2.2)
  rim.position.set(1.1, 1.9, -2.0)
  const ambient = new THREE.HemisphereLight(0xdfe8f2, 0x2a2118, 0.5)
  return [key, fill, rim, ambient]
}

/**
 * 环境贴图：64×32 的渐变 equirect 生成 PMREM。两块“柔光箱”一暖一冷，
 * 皮肤的高光因此是一条宽而柔的弧（不是点状死白），眼白和头发也才有可反射的东西。
 */
function buildEnvironment(target: THREE.WebGLRenderer): THREE.Texture {
  const canvas = document.createElement('canvas')
  canvas.width = 64
  canvas.height = 32
  const context = canvas.getContext('2d')!
  const gradient = context.createLinearGradient(0, 0, 0, 32)
  gradient.addColorStop(0, '#8a7f6e')
  gradient.addColorStop(0.45, '#39404a')
  gradient.addColorStop(1, '#0e1216')
  context.fillStyle = gradient
  context.fillRect(0, 0, 64, 32)
  context.fillStyle = '#f6ecd8'
  context.fillRect(4, 3, 15, 10)
  context.fillStyle = '#9fb6cc'
  context.fillRect(44, 5, 12, 7)
  const texture = new THREE.CanvasTexture(canvas)
  texture.mapping = THREE.EquirectangularReflectionMapping
  texture.colorSpace = THREE.SRGBColorSpace
  const pmrem = new THREE.PMREMGenerator(target)
  const env = pmrem.fromEquirectangular(texture).texture
  texture.dispose()
  pmrem.dispose()
  return env
}

function textureUrl(url: string): string {
  if (!/\.tga$/i.test(url)) return url
  const base = url.split(/[\\/]/).pop()?.toLowerCase().replace(/\.tga$/, '') ?? ''
  const mapped = TEXTURES[base]
  return mapped ? MODEL.DIR + mapped : BLANK
}

function loadModel(url: string): Promise<THREE.Group> {
  return new Promise((resolve, reject) => {
    const manager = new THREE.LoadingManager()
    manager.setURLModifier(textureUrl)
    const loader = new FBXLoader(manager)
    loader.load(
      url,
      (group) => resolve(group),
      undefined,
      (error) => reject(error instanceof Error ? error : new Error(String(error))),
    )
  })
}

/** 朝向由骨架自己决定：鼻骨相对头骨的水平偏移就是脸的朝向，把它转到 +Z 正对相机，换模型不用调数值。 */
function facingYaw(body: THREE.Group): number {
  const head = findBone(body, /Bip01[ _]Head$/i)
  const nose = findBone(body, /MNose/i)
  if (!head || !nose) return 0
  const toHead = head.getWorldPosition(new THREE.Vector3())
  const toNose = nose.getWorldPosition(new THREE.Vector3())
  const dx = toNose.x - toHead.x
  const dz = toNose.z - toHead.z
  if (Math.hypot(dx, dz) < 1e-4) return 0
  return Math.atan2(dx, dz)
}

function findBone(object: THREE.Object3D, pattern: RegExp): THREE.Object3D | null {
  let found: THREE.Object3D | null = null
  object.traverse((child) => { if (!found && child.type === 'Bone' && pattern.test(child.name)) found = child })
  return found
}

function assemble(body: THREE.Group, face: THREE.Group): void {
  if (!scene) throw new Error('渲染器未就绪')
  body.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(body)
  const height = Math.max(0.1, box.max.y - box.min.y)
  const scale = FRAME.STAND_HEIGHT / height
  const yaw = facingYaw(body)

  root = new THREE.Group()
  root.add(body)
  root.scale.setScalar(scale)
  root.rotation.y = yaw
  root.position.y = -box.min.y * scale
  baseY = root.position.y
  scene.add(root)
  root.updateMatrixWorld(true)
  topY = box.max.y * scale + root.position.y

  // 面部 fbx 与身体同一套坐标，直接并到同一个根下，再决定谁出场（两份都是全身蒙皮，同时显示会穿模）
  root.add(face)
  root.updateMatrixWorld(true)
  pickRig(body, face)
  upgradeMaterials(body)
  upgradeMaterials(face)
  poseArms(body)
  poseArms(face)
  rigBones([body, face])
  buildEyeGlints()
  collectMorphs([body, face])

  debug.meshes = []
  root.traverse((object) => {
    const mesh = object as THREE.Mesh
    if (!mesh.isMesh) return
    const materials = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]) as THREE.MeshStandardMaterial[]
    const size = new THREE.Box3().setFromObject(mesh).getSize(new THREE.Vector3())
    const dictionary = (mesh as unknown as { morphTargetDictionary?: Record<string, number> }).morphTargetDictionary
    debug.meshes.push(`${mesh.visible ? '+' : '-'}${mesh.name || mesh.type}|${mesh.type}|h=${size.y.toFixed(2)}|morph=${dictionary ? Object.keys(dictionary).length : 0}|groups=${mesh.geometry?.groups?.length ?? 0}|${materials.map((m) => `${m?.name ?? ''}:map${m?.map ? 1 : 0}:col${m?.color?.getHexString() ?? ''}`).join(',')}`)
  })
  root.traverse((object) => { object.frustumCulled = false })
  root.updateMatrixWorld(true)
  debug.bones = []
  root.traverse((object) => {
    if (object.type !== 'Bone' || !/UpperArm|Forearm|Hand$|Clavicle|Head$/i.test(object.name)) return
    const point = object.getWorldPosition(new THREE.Vector3())
    debug.bones.push(`${object.name}:${point.x.toFixed(2)},${point.y.toFixed(2)},${point.z.toFixed(2)}`)
  })
  frameCamera()
  clock = 0
  blinkStart = -1
  nextBlink = MOTION.BLINK_GAP_MIN + Math.random() * (MOTION.BLINK_GAP_MAX - MOTION.BLINK_GAP_MIN)
  if (import.meta.env.DEV) {
    const probe = window as unknown as Record<string, unknown>
    probe.__humanDebug = debug
    probe.__humanScene = scene
    probe.__humanCamera = camera
  }
  start()
}

/**
 * 两份 fbx 都是全身蒙皮（面部那份带 175 个 blendshape），谁带 morph 就让谁出场：
 * 面部那份几乎总是赢，身体 fbx 退化成兜底素材；只有面部确实是“纯头部”时才留身体、把面部里非头部网格藏掉。
 */
function pickRig(body: THREE.Group, face: THREE.Group): void {
  const spelled: THREE.Mesh[] = []
  const heads: THREE.Mesh[] = []
  face.traverse((object) => {
    const mesh = object as THREE.Mesh
    if (!mesh.isMesh) return
    const size = new THREE.Box3().setFromObject(mesh).getSize(new THREE.Vector3())
    const dictionary = (mesh as unknown as { morphTargetDictionary?: Record<string, number> }).morphTargetDictionary
    if (dictionary && Object.keys(dictionary).length && size.y > FRAME.STAND_HEIGHT * 0.8) spelled.push(mesh)
    if (size.y < 0.45) heads.push(mesh)
  })
  if (spelled.length) {
    body.visible = false
    console.info('[HumanPresenter] 使用面部 fbx 的全身蒙皮作为主模型（带 blendshape），身体 fbx 仅作兜底')
    return
  }
  if (!heads.length) return
  face.traverse((object) => {
    const mesh = object as THREE.Mesh
    if (mesh.isMesh && !heads.includes(mesh)) mesh.visible = false
  })
  hideBodyHead(body)
}

function hideBodyHead(body: THREE.Group): void {
  body.traverse((object) => {
    const mesh = object as THREE.Mesh
    if (mesh.isMesh && /head/i.test(mesh.name) && !/hair/i.test(mesh.name)) mesh.visible = false
  })
}

/**
 * 材质档位：这套模型只有三份材质（m005_body / m005_head / m005_opacity）。
 * 必须按**材质名**分派——三个网格名都是 …_bones_opacity，拿网格名判断会把西装和脸一起当成头发
 * 套上 alphaTest + DoubleSide + roughness 0.95，皮肤于是没有高光、发际线被硬切。
 */
type Tier = 'hair' | 'head' | 'body'

function tierOf(name: string): Tier {
  if (/opacity|hair/i.test(name)) return 'hair'
  if (/head|face|skin/i.test(name)) return 'head'
  return 'body'
}

type Profile = {
  roughness: number
  envMapIntensity: number
  normalScale: number
  emissive: number
  emissiveIntensity: number
  sheen?: { value: number; roughness: number; color: number }
}

const PROFILES: Record<Tier, Profile> = {
  // 皮肤：0.55 让高光散成一片而不是镜面点；一点暖自发光近似次表面散射，压掉“蜡像死白”
  head: { roughness: 0.55, envMapIntensity: 1.35, normalScale: 0.7, emissive: 0xffd6bd, emissiveIntensity: 0.035 },
  // 西装：布面粗糙度 0.8 + 一丝 sheen，领口和肩线才有织物的绒光
  body: { roughness: 0.8, envMapIntensity: 0.8, normalScale: 0.55, emissive: 0x000000, emissiveIntensity: 0, sheen: { value: 0.15, roughness: 0.55, color: 0xf3e8d8 } },
  // 头发：低粗糙度 + 环境反射近似各向异性高光。alphaTest 0.4 保持不透明裁剪——
  // 发片是 alpha 渐变带，一旦开透明混合，掠射角的环境反射会糊成一圈白雾（已截图验证）
  hair: { roughness: 0.42, envMapIntensity: 0.95, normalScale: 0.5, emissive: 0x0a0705, emissiveIntensity: 0.02, sheen: { value: 0.2, roughness: 0.45, color: 0x6f5844 } },
}

/** 统一转成 PBR：FBX 里的 Phong 高光在三点光下会发塑料光，按皮肤/布料/头发三档重新配参数。 */
function upgradeMaterials(group: THREE.Group): void {
  group.traverse((object) => {
    const mesh = object as THREE.Mesh
    if (!mesh.isMesh) return
    const sources = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]) as THREE.MeshPhongMaterial[]
    const upgraded = sources.map((previous) => upgrade(previous, mesh.name))
    for (const previous of sources) previous?.dispose()
    mesh.material = Array.isArray(mesh.material) ? upgraded : upgraded[0]
  })
}

/** 单个材质：贴图自带颜色时把 DiffuseColor 归到白色，否则 FBX 里的黑色 Diffuse 会把整张皮肤贴图乘黑。 */
function upgrade(previous: THREE.MeshPhongMaterial | undefined, meshName: string): THREE.MeshStandardMaterial {
  const name = previous?.name ?? meshName
  const tier = tierOf(previous?.name || meshName)
  const profile = PROFILES[tier]
  const color = previous?.color?.clone() ?? new THREE.Color(0xffffff)
  if (previous?.map && Math.max(color.r, color.g, color.b) < 0.06) color.set(0xffffff)
  const base = { name, map: previous?.map ?? null, color, roughness: profile.roughness, metalness: 0 }
  const material = profile.sheen
    ? new THREE.MeshPhysicalMaterial({
      ...base,
      sheen: profile.sheen.value,
      sheenRoughness: profile.sheen.roughness,
      sheenColor: new THREE.Color(profile.sheen.color),
    })
    : new THREE.MeshStandardMaterial(base)
  material.envMapIntensity = profile.envMapIntensity
  material.emissive = new THREE.Color(profile.emissive)
  material.emissiveIntensity = profile.emissiveIntensity
  if (material.map) material.map.colorSpace = THREE.SRGBColorSpace
  if (tier === 'hair') {
    // 0.4 的硬裁剪比 0.35 更干净地切掉发片边缘的半透明胶带感，同时不引入透明排序问题
    material.transparent = false
    material.alphaTest = 0.4
    material.side = THREE.DoubleSide
  } else {
    attachNormal(material, tier)
  }
  if (tier === 'body') dyeTie(material)
  if (!material.map) material.color.set(0xb98f74)
  debug.materials.push(`${name}|tier=${tier}|r=${profile.roughness}|env=${profile.envMapIntensity}|normal=${material.normalMap ? profile.normalScale : 'none'}|map=${material.map ? 1 : 0}|transparent=${material.transparent}`)
  return material
}

/** 法线贴图：FBX 只声明了 diffuse，法线文件虽然随仓库提供却没被绑上，这里按档位显式加载并沿用 diffuse 的 UV 设置。 */
function attachNormal(material: THREE.MeshStandardMaterial, tier: Tier): void {
  const file = tier === 'head' ? 'm005_head_normal.webp' : 'm005_body_normal.webp'
  const texture = new THREE.TextureLoader().load(MODEL.DIR + file)
  texture.colorSpace = THREE.NoColorSpace
  const map = material.map
  if (map) {
    texture.wrapS = map.wrapS
    texture.wrapT = map.wrapT
    texture.repeat.copy(map.repeat)
    texture.offset.copy(map.offset)
    texture.flipY = map.flipY
  }
  material.normalMap = texture
  material.normalScale.set(PROFILES[tier].normalScale, PROFILES[tier].normalScale)
}

const tinted = new WeakMap<THREE.Texture, THREE.Texture>()

/**
 * 领带染色：大红色太抢眼，压成深酒红。领带是烘进 m005_body_color 的，改不了材质颜色，
 * 所以拷一份贴图到 canvas，只在领带的 UV 岛内把高饱和红按亮度重映射（几何与 UV 完全不动）。
 */
function dyeTie(material: THREE.MeshStandardMaterial): void {
  const source = material.map
  if (!source) { debug.tint = 'no-map'; return }
  const cached = tinted.get(source)
  if (cached) { material.map = cached; return }
  // FBXLoader 的贴图此刻可能还没解码完（texture.image 为空），所以自己再取一次同一张 webp，
  // 它在浏览器缓存里，成本只有一次 2D 画布读写
  const uv = {
    wrapS: source.wrapS,
    wrapT: source.wrapT,
    repeat: source.repeat.clone(),
    offset: source.offset.clone(),
    flipY: source.flipY,
  }
  const apply = (image: HTMLImageElement): void => {
    const width = image.naturalWidth || image.width
    const height = image.naturalHeight || image.height
    if (!width || !height) return
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) return
    context.drawImage(image, 0, 0)
    const data = context.getImageData(0, 0, width, height)
    const pixels = data.data
    const keep = 1 - TIE.MIX
    for (let y = Math.floor(height * TIE.Y0); y < Math.ceil(height * TIE.Y1); y += 1) {
      for (let x = Math.floor(width * TIE.X0); x < Math.ceil(width * TIE.X1); x += 1) {
        const offset = (y * width + x) * 4
        const r = pixels[offset]
        const g = pixels[offset + 1]
        const b = pixels[offset + 2]
        const max = Math.max(r, g, b)
        if (max < TIE.RED || r <= g * TIE.RATIO_G || r <= b * TIE.RATIO_B) continue
        if ((max - Math.min(r, g, b)) / max < TIE.SAT) continue
        const luma = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        pixels[offset] = (r / 255) * keep * 255 + Math.min(1, luma * TIE.WINE.R) * TIE.MIX * 255
        pixels[offset + 1] = (g / 255) * keep * 255 + luma * TIE.WINE.G * TIE.MIX * 255
        pixels[offset + 2] = (b / 255) * keep * 255 + luma * TIE.WINE.B * TIE.MIX * 255
      }
    }
    context.putImageData(data, 0, 0)
    const texture = new THREE.CanvasTexture(canvas)
    texture.colorSpace = THREE.SRGBColorSpace
    texture.wrapS = uv.wrapS
    texture.wrapT = uv.wrapT
    texture.repeat.copy(uv.repeat)
    texture.offset.copy(uv.offset)
    texture.flipY = uv.flipY
    tinted.set(source, texture)
    material.map = texture
    material.needsUpdate = true
    debug.tint = `${width}x${height}`
  }
  const image = new Image()
  image.onload = () => apply(image)
  image.onerror = () => { debug.tint = 'load-failed' }
  image.src = MODEL.DIR + TEXTURES.m005_body_color
}

/** 上臂从 T-pose 压到体侧：按“骨骼当前世界朝向 → 目标世界朝向”求旋转，绕开 3ds Max Biped 的怪轴。 */
function poseArms(body: THREE.Group): void {
  aimBone(body, /Bip01[ _]L[ _]UpperArm$/i, new THREE.Vector3(POSE.ARM_OUT, -1, POSE.ARM_FORWARD))
  aimBone(body, /Bip01[ _]R[ _]UpperArm$/i, new THREE.Vector3(-POSE.ARM_OUT, -1, POSE.ARM_FORWARD))
  bendElbow(body, /Bip01[ _]L[ _]Forearm$/i, -POSE.ELBOW)
  bendElbow(body, /Bip01[ _]R[ _]Forearm$/i, -POSE.ELBOW)
  body.updateMatrixWorld(true)
}

function aimBone(body: THREE.Group, pattern: RegExp, dir: THREE.Vector3): void {
  const bone = findBone(body, pattern)
  if (!bone || !bone.parent) return
  const child = bone.children.find((item) => item.type === 'Bone') ?? bone.children[0]
  bone.updateMatrixWorld(true)
  const from = child
    ? child.getWorldPosition(new THREE.Vector3()).sub(bone.getWorldPosition(new THREE.Vector3())).normalize()
    : new THREE.Vector3(0, -1, 0)
  const to = dir.clone().normalize()
  const world = new THREE.Quaternion().setFromUnitVectors(from, to)
  const parentWorld = bone.parent.getWorldQuaternion(new THREE.Quaternion())
  bone.quaternion.copy(parentWorld.clone().invert().multiply(world).multiply(parentWorld).multiply(bone.quaternion))
  bone.updateMatrixWorld(true)
}

/** 肘部略微前压，手臂不贴着身体也不会横出手臂。 */
function bendElbow(body: THREE.Group, pattern: RegExp, angle: number): void {
  const bone = findBone(body, pattern)
  if (!bone || !bone.parent) return
  const world = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), angle)
  const parentWorld = bone.parent.getWorldQuaternion(new THREE.Quaternion())
  bone.quaternion.copy(parentWorld.clone().invert().multiply(world).multiply(parentWorld).multiply(bone.quaternion))
  bone.updateMatrixWorld(true)
}

const RIG_PATTERNS = {
  spine: /Bip01[ _]Spine2$/i,
  shoulders: /Bip01[ _][LR][ _]Clavicle$/i,
  neck: /Bip01[ _]Neck$/i,
  head: /Bip01[ _]Head$/i,
}

/** 记录要摆动的骨骼与它们的静止四元数；身体/面部两套骨架同名，一起动才不会错位。 */
function rigBones(groups: THREE.Group[]): void {
  rig.spine = []
  rig.shoulders = []
  rig.neck = []
  rig.head = []
  jawBones.length = 0
  for (const group of groups) {
    group.traverse((object) => {
      if (object.type !== 'Bone') return
      const entry = { bone: object, rest: object.quaternion.clone() }
      if (RIG_PATTERNS.spine.test(object.name)) rig.spine.push(entry)
      else if (RIG_PATTERNS.shoulders.test(object.name)) rig.shoulders.push(entry)
      else if (RIG_PATTERNS.neck.test(object.name)) rig.neck.push(entry)
      else if (RIG_PATTERNS.head.test(object.name)) rig.head.push(entry)
      if (/Bip01[ _]MJaw$/i.test(object.name)) jawBones.push({ bone: object, rest: object.quaternion.clone(), sign: 1 })
    })
  }
}

/** 找 morph：先按语义正则匹配眨眼（左右成对优先）、张嘴（jawOpen 类），找不到就留空，不做贴图伪口型。 */
function collectMorphs(groups: THREE.Group[]): void {
  const keys: { key: string; morph: Morph }[] = []
  for (const group of groups) {
    group.traverse((object) => {
      const mesh = object as THREE.Mesh
      if (!mesh.isMesh) return
      const dictionary = (mesh as unknown as { morphTargetDictionary?: Record<string, number> }).morphTargetDictionary
      if (!dictionary) return
      for (const [key, index] of Object.entries(dictionary)) keys.push({ key, morph: { mesh, index } })
    })
  }
  debug.morphKeys = [...new Set(keys.map((item) => item.key))]
  console.info('[HumanPresenter] morphTargetDictionary 键名：', debug.morphKeys)

  const pickPair = (left: RegExp, right: RegExp, leftTarget: Morph[], rightTarget: Morph[]): void => {
    if (leftTarget.length) return
    const leftHits = keys.filter((item) => left.test(item.key) && !/wide|squeeze|frown/i.test(item.key))
    const rightHits = keys.filter((item) => right.test(item.key) && !/wide|squeeze|frown/i.test(item.key))
    if (!leftHits.length || !rightHits.length) return
    leftTarget.push(...leftHits.slice(0, 2).map((item) => item.morph))
    rightTarget.push(...rightHits.slice(0, 2).map((item) => item.morph))
  }

  pickPair(/eye[\s_-]?blink[\s_-]?left/i, /eye[\s_-]?blink[\s_-]?right/i, morphs.blinkLeft, morphs.blinkRight)
  if (!morphs.blinkLeft.length) pickPair(/eye[\s_-]?left[\s_-]?blink/i, /eye[\s_-]?right[\s_-]?blink/i, morphs.blinkLeft, morphs.blinkRight)
  if (!morphs.blinkLeft.length) pickPair(/AU_43_L/i, /AU_43_R/i, morphs.blinkLeft, morphs.blinkRight)
  if (!morphs.blinkLeft.length) pickPair(/blink[\s_-]?l\b/i, /blink[\s_-]?r\b/i, morphs.blinkLeft, morphs.blinkRight)
  if (!morphs.blinkLeft.length) {
    const single = keys.filter((item) => /blink|eyeclosed|eye_closed/i.test(item.key) && !/wide|squeeze|frown/i.test(item.key))
    if (single.length) { morphs.blinkAll.push(single[0].morph); debug.blinkKeys.push(single[0].key) }
  } else {
    debug.blinkKeys.push(...uniqueNames([...morphs.blinkLeft, ...morphs.blinkRight], keys))
  }

  const jawCandidate = keys.find((item) => /jaw[\s_-]?open/i.test(item.key))
    ?? keys.find((item) => /jawdrop|jaw_drop|jaw_dropper/i.test(item.key))
    ?? keys.find((item) => /mouth[\s_-]?open|mouthopen/i.test(item.key))
  if (jawCandidate) { morphs.jaw.push(jawCandidate.morph); debug.jawKeys.push(jawCandidate.key) }
  console.info('[HumanPresenter] 眨眼 morph：', debug.blinkKeys, '张嘴 morph：', debug.jawKeys)
}

function uniqueNames(list: Morph[], keys: { key: string; morph: Morph }[]): string[] {
  return keys.filter((item) => list.some((morph) => morph.mesh === item.morph.mesh && morph.index === item.morph.index)).map((item) => item.key)
}

/** 找可见骨架里的眼球骨（Bip01 LEye / REye）；两份 fbx 都有同名骨，只取当前出场那份。 */
function eyeBone(side: 'L' | 'R'): THREE.Object3D | null {
  const pattern = new RegExp(`^Bip01[ _]${side}Eye$`, 'i')
  let found: THREE.Object3D | null = null
  root?.traverse((object) => {
    if (found || object.type !== 'Bone' || !pattern.test(object.name)) return
    let shown = true
    object.traverseAncestors((parent) => { if (!parent.visible) shown = false })
    if (shown) found = object
  })
  return found
}

/**
 * 眼球前方各挂一个极小的加色 sprite：位置逐帧从眼球骨取，再朝相机方向推出 4mm。
 * 大眼白+贴图瞳孔在三点光下没有可反射的东西，所以眼神是死的；这一点高光是最省的一招。
 */
function buildEyeGlints(): void {
  disposeGlints()
  if (!scene) return
  const texture = glintSpriteTexture()
  for (const side of ['L', 'R'] as const) {
    const bone = eyeBone(side)
    if (!bone) continue
    // 关掉 depthTest：眼球在网格里是内凹的眼窝，高光点只要落在里面就会被自己挡掉；
    // 这个镜头固定、头部只微摆 ±2°，不会转到背面，代价可以接受（眨眼时整只隐藏，见 updateEyeGlints）
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      opacity: GLINT.OPACITY,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      depthTest: false,
      toneMapped: false,
    }))
    // sprite 挂在 scene 上（世界尺度 = 米），尺寸直接给 GLINT.SIZE，不能按根节点缩放换算
    sprite.scale.setScalar(GLINT.SIZE)
    sprite.renderOrder = 2
    scene.add(sprite)
    glints.push({ sprite, bone })
  }
  if (glints.length) updateEyeGlints()
}

function glintSpriteTexture(): THREE.Texture {
  if (glintTexture) return glintTexture
  const canvas = document.createElement('canvas')
  canvas.width = 64
  canvas.height = 64
  const context = canvas.getContext('2d')!
  const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32)
  gradient.addColorStop(0, 'rgba(255,255,255,1)')
  gradient.addColorStop(0.32, 'rgba(255,246,236,0.72)')
  gradient.addColorStop(1, 'rgba(255,246,236,0)')
  context.fillStyle = gradient
  context.fillRect(0, 0, 64, 64)
  glintTexture = new THREE.CanvasTexture(canvas)
  glintTexture.colorSpace = THREE.SRGBColorSpace
  return glintTexture
}

function updateEyeGlints(): void {
  if (!camera || !glints.length) return
  for (const glint of glints) {
    glint.bone.getWorldPosition(glintA)
    glintB.copy(camera.position).sub(glintA).normalize()
    glint.sprite.position.copy(glintA).addScaledVector(glintB, GLINT.OFFSET)
    glint.sprite.position.y += GLINT.SIZE * 0.3
    // 眨眼时眼睑是头部网格的一部分，depthTest 已关，必须自己把高光藏起来，否则会是浮在眼皮上的白点
    glint.sprite.visible = debug.blink < 0.35
  }
}

function disposeGlints(): void {
  for (const glint of glints) {
    scene?.remove(glint.sprite)
    ;(glint.sprite.material as THREE.SpriteMaterial).dispose()
  }
  glints.length = 0
}

function resize(): void {
  if (!renderer || !camera || !container.value) return
  const width = container.value.clientWidth || 1
  const height = container.value.clientHeight || 1
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MOTION.MAX_DPR))
  renderer.setSize(width, height, false)
  camera.aspect = width / height
  frameCamera()
}

/** 相机固定：按容器宽高比换算 fov 与距离，三种容器尺寸下都保持同一套完整半身取景。 */
function frameCamera(): void {
  if (!camera) return
  const aspect = Math.max(0.35, camera.aspect)
  const fov = THREE.MathUtils.clamp(
    FRAME.FOV_BASE + Math.max(0, FRAME.NARROW_ASPECT - aspect) * FRAME.FOV_SLOPE,
    FRAME.FOV_BASE,
    FRAME.FOV_MAX,
  )
  camera.fov = fov
  camera.updateProjectionMatrix()
  const half = Math.tan((fov / 2) * (Math.PI / 180))
  const byHeight = (FRAME.VISIBLE_HEIGHT / 2) / half
  const byWidth = (FRAME.VISIBLE_WIDTH / 2) / (half * aspect)
  const distance = Math.max(byHeight, byWidth)
  const top = topY + FRAME.VISIBLE_HEIGHT * 0.08
  const focusY = top - FRAME.VISIBLE_HEIGHT / 2
  camera.position.set(0, focusY, distance)
  camera.lookAt(0, focusY, 0)
  debug.frame = { fov, distance, aspect, top, bottom: top - FRAME.VISIBLE_HEIGHT }
  // 取景校验：头顶与左右肩在 NDC 里的位置，|x|<1 且 y<1 表示没有被裁掉
  camera.updateMatrixWorld(true)
  const project = (x: number, y: number): THREE.Vector3 => new THREE.Vector3(x, y, 0).project(camera!)
  const headPoint = project(0, topY)
  const leftShoulder = project(-0.28, 1.3)
  const rightShoulder = project(0.28, 1.3)
  debug.bezel = {
    headTop: headPoint.y,
    shoulder: Math.max(Math.abs(leftShoulder.x), Math.abs(rightShoulder.x)),
  }
}

function start(): void {
  if (raf || disposed || state.value !== 'ready') return
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
function onFocus(): void { if (!document.hidden) start() }

function frame(now: number): void {
  raf = requestAnimationFrame(frame)
  if (!renderer || !scene || !camera || !root) return
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

function pose(entries: BoneRig[], x: number, y: number, z: number): void {
  if (!x && !y && !z) { for (const entry of entries) entry.bone.quaternion.copy(entry.rest); return }
  const delta = new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z))
  for (const entry of entries) entry.bone.quaternion.copy(entry.rest).multiply(delta)
}

function update(dt: number): void {
  if (!root || debug.pause) return
  clock += dt
  const t = clock
  const reduced = reduceMotion.matches
  const speaking = debug.override.speaking ?? props.speaking
  const listening = debug.override.listening ?? props.listening
  sampleAudio(dt)

  const level = debug.override.level ?? audio.level
  const open = speaking ? Math.max(0, Math.min(1, level)) : 0
  debug.level = level
  debug.mode = speaking ? 'speaking' : listening ? 'listening' : 'idle'

  const breath = reduced ? 0 : Math.sin((t / MOTION.BREATH_SECONDS) * Math.PI * 2)
  root.position.y = baseY + breath * MOTION.BREATH_LIFT
  pose(rig.spine, breath * MOTION.CHEST_BREATH, 0, 0)
  pose(rig.shoulders, breath * MOTION.SHOULDER_BREATH, 0, 0)

  const sway = reduced ? 0 : Math.sin((t / MOTION.SWAY_SECONDS) * Math.PI * 2) * (props.active ? 1 : 0.6)
  const tilt = !reduced && listening ? MOTION.LISTEN_TILT : 0
  const nod = !reduced && speaking ? Math.sin(t * 5.4) * MOTION.NOD * open : 0
  pose(rig.neck, sway * MOTION.SWAY_PITCH * 0.5 + nod * 0.4, sway * MOTION.SWAY_YAW * 0.5, tilt * 0.4)
  pose(rig.head, sway * MOTION.SWAY_PITCH + nod, sway * MOTION.SWAY_YAW, tilt)

  const blink = debug.override.blink ?? blinkValue(t, listening)
  const jaw = open * MOTION.JAW_GAIN
  debug.blink = blink
  debug.jaw = jaw
  applyMorph(morphs.blinkLeft, blink)
  applyMorph(morphs.blinkRight, blink)
  applyMorph(morphs.blinkAll, blink)
  applyMorph(morphs.jaw, jaw)
  if (!morphs.jaw.length) animateJawBone(jaw)
  updateEyeGlints()

  fpsFrames += 1
  fpsWindow += dt
  if (fpsWindow >= 1) {
    debug.fps = Math.round(fpsFrames / fpsWindow)
    fpsFrames = 0
    fpsWindow = 0
  }
}

function applyMorph(list: Morph[], value: number): void {
  for (const item of list) {
    const influences = item.mesh.morphTargetInfluences
    if (influences && item.index < influences.length) influences[item.index] = value
  }
}

/** 没有 mouth morph 时只用下颌骨极轻微开合，绝不拿贴图变形伪造口型。 */
function animateJawBone(value: number): void {
  for (const entry of jawBones) {
    entry.bone.quaternion.copy(entry.rest).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), value * 0.09 * entry.sign))
  }
}

/** 每 3–7 秒眨一次；倾听时更慢。0 → 1 → 0 的 160ms 曲线。 */
function blinkValue(t: number, listening: boolean): number {
  if (blinkStart < 0 && t >= nextBlink) blinkStart = t
  if (blinkStart < 0) return 0
  const progress = (t - blinkStart) / MOTION.BLINK_DURATION
  if (progress >= 1) {
    blinkStart = -1
    const gap = MOTION.BLINK_GAP_MIN + Math.random() * (MOTION.BLINK_GAP_MAX - MOTION.BLINK_GAP_MIN)
    nextBlink = t + (listening ? gap * MOTION.LISTEN_BLINK_SCALE : gap)
    return 0
  }
  return progress < 0.5 ? progress * 2 : (1 - progress) * 2
}

/** 每帧采样真实音量（TTS 播放音轨的 AnalyserNode），与 PhotoPresenter / Live2D 同一套 RMS → 0..1。 */
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
  const tau = target > audio.level ? MOTION.AUDIO_SMOOTH : MOTION.AUDIO_RELEASE
  audio.level += (target - audio.level) * (1 - Math.exp(-dt / tau))
}

function observeAudio(source: AnalyserNode | null): void {
  audio.analyser = source
  audio.bins = source ? new Float32Array(source.fftSize) : null
  if (!source) audio.level = 0
}

function finishAudio(): void {
  observeAudio(null)
  applyMorph(morphs.jaw, 0)
  animateJawBone(0)
}

function disconnect(): void {
  finishAudio()
  stop()
}

function disposeTree(object: THREE.Object3D): void {
  object.traverse((child) => {
    const mesh = child as THREE.Mesh
    if (!mesh.isMesh) return
    mesh.geometry?.dispose()
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    for (const material of materials) {
      if (!material) continue
      const item = material as THREE.MeshStandardMaterial
      item.map?.dispose()
      item.normalMap?.dispose()
      item.dispose()
    }
  })
}

function teardown(): void {
  stop()
  disposeGlints()
  glintTexture?.dispose()
  glintTexture = null
  if (root) { disposeTree(root); scene?.remove(root); root = null }
  observer?.disconnect()
  observer = null
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('blur', onBlur)
  window.removeEventListener('focus', onFocus)
  if (renderer) {
    scene?.environment?.dispose()
    renderer.dispose()
    renderer.domElement.remove()
    renderer = null
  }
  scene = null
  camera = null
  rig.spine = []; rig.shoulders = []; rig.neck = []; rig.head = []
  morphs.blinkLeft = []; morphs.blinkRight = []; morphs.blinkAll = []; morphs.jaw = []
}

onBeforeUnmount(() => {
  disposed = true
  teardown()
  emit('ready', false)
})

defineExpose({ connect, disconnect, observeAudio, finishAudio, isConnected: () => state.value === 'ready' })
</script>

<template>
  <div class="human-presenter" role="img" :aria-label="label">
    <div ref="container" class="human-canvas" aria-hidden="true" />
    <div class="human-vignette" aria-hidden="true" />
    <span v-if="state === 'loading'" class="human-placeholder" role="status">正在准备面试官…</span>
    <div v-if="state === 'error'" class="human-error" role="status">
      <span>3D 面试官加载失败</span>
      <button type="button" @click="connect">重新加载</button>
    </div>
    <span v-else class="human-credit">Business Male 01 · Microsoft Rocketbox (MIT)</span>
  </div>
</template>

<style scoped>
.human-presenter { position: relative; width: 100%; height: 100%; overflow: hidden; background: radial-gradient(ellipse at 50% 26%, #2b333b 0, #1d242a 48%, #10151a 100%); }
.human-canvas { position: absolute; inset: 0; }
.human-canvas :deep(canvas) { display: block; width: 100%; height: 100%; }
.human-placeholder { position: absolute; inset: 0; display: grid; place-items: center; color: #c3ccd4; font-size: 13px; }
.human-error { position: absolute; inset: auto 16px 38px; display: grid; justify-items: center; gap: 10px; padding: 12px; border-radius: 8px; background: #26323be6; color: #fff; font-size: 12px; }
.human-error button { padding: 5px 10px; border: 1px solid #ffffff70; border-radius: 6px; background: transparent; color: #fff; cursor: pointer; }
/* 极轻的暗角：远景压暗、面部留亮，人物从背景里“浮”出来一层（纯 CSS，不上后处理） */
.human-vignette { position: absolute; inset: 0; pointer-events: none; background: radial-gradient(ellipse 76% 70% at 50% 40%, #0000 40%, #00000026 72%, #0000008c 100%); }
/* 署名从前移右上角（那里被自拍小窗盖住），并改成悬停才完全显示 */
.human-credit { position: absolute; right: 12px; top: 10px; padding: 2px 6px; border-radius: 4px; background: #0b0f13a8; color: #c9d4dc; font-size: 10px; opacity: .42; transition: opacity .18s ease; }
.human-presenter:hover .human-credit, .human-credit:focus-visible { opacity: 1; }
</style>
