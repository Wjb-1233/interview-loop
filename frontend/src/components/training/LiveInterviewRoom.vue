<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { Hand, Maximize2, Mic, Minimize2, PhoneOff, RotateCcw } from 'lucide-vue-next'

import PermissionDialog from '@/components/media/PermissionDialog.vue'
import AvatarPresenter from '@/components/media/AvatarPresenter.vue'
import { useInterviewPlayback } from '@/composables/useInterviewPlayback'
import { useInterviewRecording } from '@/composables/useInterviewRecording'
import { useInterviewSubmission } from '@/composables/useInterviewSubmission'
import { api, errorMessage } from '@/lib/api'
import type { ApiEnvelope, Scene } from '@/lib/types'

type RoomPhase = 'connecting' | 'live' | 'error' | 'saving'
type Engine = 'doubao' | 'pipeline'
type MicIssue = '' | 'permission' | 'device' | 'busy' | 'unsupported'

const props = defineProps<{
  captureMode: 'voice' | 'video'
  scene: Scene | null
  engine: Engine
  durationMinutes: number
  depth?: 'STANDARD' | 'THREE_LAYER' | 'PRESSURE'
  preparedSessionId?: string
  exitError?: string
}>()

const emit = defineEmits<{ ended: [sessionId: string]; prepared: [sessionId: string]; finishing: []; failed: [message: string]; switchVoice: [] }>()

const status = shallowRef<RoomPhase>('connecting')
const effectiveEngine = shallowRef<Engine>(props.engine)
const attemptId = shallowRef(props.preparedSessionId ?? '')
const interviewContext = shallowRef<{ instructions: string; openingLine: string; minimumRounds?: number } | null>(null)
const reportPending = shallowRef(false)
const fallbackNotice = shallowRef('')
let fallbackTried = false
const turnState = shallowRef<'idle' | 'heard' | 'thinking' | 'speaking'>('idle')
const error = shallowRef('')
const heard = shallowRef('')
const reply = shallowRef('')
const rounds = shallowRef(0)
const micOn = shallowRef(false)
// 麦克风为什么没声音：一律给用户可执行的原因，不做静默失败
const micIssue = shallowRef<MicIssue>('')
const micLevel = shallowRef(0)
const silentSeconds = shallowRef(0)
const remaining = shallowRef(props.durationMinutes * 60)
const preview = ref<HTMLVideoElement | null>(null)
const roomElement = useTemplateRef<HTMLElement>('roomElement')
const immersive = shallowRef(true)
const avatar = useTemplateRef<InstanceType<typeof AvatarPresenter>>('avatar')
const { speakerActive, replayActive, playPcm, playPcmBinary, replaySpeech, stopPlayback, disposePlayback, playbackExpired, resumePlayback, preparePlayback } = useInterviewPlayback(
  () => avatar.value,
  () => { turnState.value = 'speaking' },
  () => { if (turnState.value === 'speaking') turnState.value = 'idle' },
)
const { startRecording, finishRecording, stopRecording, recordingBlob } = useInterviewRecording()
const { uploadedSessionId, submitReport } = useInterviewSubmission()

// 申请麦克风/摄像头的两步交互：先明说「请求已发出」，被拒绝时换成三步引导
const micWaiting = ref(false)
const showMicGuide = ref(false)
const micDevices = computed<Array<'camera' | 'microphone'>>(() =>
  isVideo.value ? ['camera', 'microphone'] : ['microphone'],
)

const turns = shallowRef<Array<{ question: string; answer: string; startMs?: number; endMs?: number }>>([])
let wsTicket = ''
let lastAnswer = ''
let partialAnswer = ''
let lastQuestion = ''
let startedAt = 0
let turnStartedAt = 0
let pendingTiming: { startMs: number; endMs: number } | null = null

/** 等形象的硬上限：比 Simli 的 8 秒建连超时多 1 秒，落回本地形象时也不会拖住开场。 */
const AVATAR_WAIT_MS = 9000

let socket: WebSocket | null = null
let audioContext: AudioContext | null = null
let micStream: MediaStream | null = null
let processor: ScriptProcessorNode | null = null
let source: MediaStreamAudioSourceNode | null = null
let lastLevelAt = 0
let pending = new Float32Array(0)
let countdown: ReturnType<typeof setInterval> | null = null
let closing = false
let disposed = false
let attemptDiscarded = false
let sessionSeq = 0

const isVideo = computed(() => props.captureMode === 'video')
const timeLabel = computed(() => {
  const total = Math.max(0, remaining.value)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
})
const interviewerSpeaking = computed(() => status.value === 'live' && (speakerActive.value || replayActive.value))
const interviewerListening = computed(() => status.value === 'live' && micOn.value && !interviewerSpeaking.value && turnState.value === 'idle')

const liveStatus = computed(() => {
  if (status.value === 'connecting') return '正在接通面试官…'
  if (status.value === 'saving') return '正在整理报告…'
  if (status.value === 'error') return '连接中断'
  if (interviewerSpeaking.value || turnState.value === 'speaking') return '面试官正在说…'
  if (turnState.value === 'heard' || turnState.value === 'thinking') return '已收到你的回答，面试官正在想下一个问题…'
  if (!micOn.value) return '等待麦克风'
  if (silentSeconds.value >= 8) return '还没听到声音：确认麦克风没静音、没选错设备'
  if (micLevel.value > 0.03) return '正在听你说…'
  return rounds.value === 0 ? '请直接开口回答' : '轮到你了，直接说'
})

const statusLabel = computed(() => {
  if (status.value === 'connecting') return '正在接通面试官'
  if (status.value === 'saving') return '正在整理报告'
  if (status.value === 'error') return '连接异常'
  return isVideo.value ? '视频面试进行中' : '语音面试进行中'
})

function instructions(): string { return interviewContext.value?.instructions ?? '你是一名中文面试官，每轮只问一个问题，围绕本场岗位与经历追问。' }
function openingLine(): string { return interviewContext.value?.openingLine ?? props.scene?.openingLine ?? '你好，请先做个自我介绍。' }

function wsUrl(): string {
  const base = import.meta.env.VITE_API_BASE ?? '/api/v1'
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  // WS 带不了 Authorization 头，用登录后取到的短时票据换连
  const query = new URLSearchParams({ ticket: wsTicket })
  if (effectiveEngine.value === 'pipeline') {
    query.set('depth', props.depth ?? 'STANDARD')
    if (attemptId.value) query.set('sessionId', attemptId.value)
    if (props.scene?.id) query.set('sceneId', props.scene.id)
    return `${scheme}://${location.host}${base}/voice/ws/pipeline?${query.toString()}`
  }
  return `${scheme}://${location.host}${base}/voice/ws?${query.toString()}`
}

async function fetchTicket(): Promise<boolean> {
  try {
    const issued = await api.post<ApiEnvelope<{ ticket: string; expiresIn: number }>>('/voice/ws-ticket')
    wsTicket = issued.data.data.ticket
    return Boolean(wsTicket)
  } catch {
    return false
  }
}

function toBase64(buffer: ArrayBuffer): string {
  let binary = ''
  const bytes = new Uint8Array(buffer)
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}







function handleEvent(raw: string): void {
  let event: Record<string, unknown>
  try {
    event = JSON.parse(raw)
  } catch {
    return
  }
  const type = String(event.type ?? '')
  if (effectiveEngine.value === 'pipeline') {
    if (type === 'user' && event.text) {
      heard.value = String(event.text)
      reply.value = ''
      turnState.value = 'heard'
      lastAnswer = String(event.text)
      pendingTiming = { startMs: turnStartedAt || startedAt, endMs: Date.now() }
      turnStartedAt = Date.now()
    } else if (type === 'assistant_delta' && event.text) {
      const wasEmpty = !reply.value
      reply.value = `${reply.value}${event.text}`
      if (wasEmpty) turnState.value = 'speaking'
    } else if (type === 'assistant_end') {
      if (lastAnswer.trim()) {
        turns.value = [...turns.value, {
          question: lastQuestion,
          answer: lastAnswer,
          startMs: pendingTiming?.startMs,
          endMs: pendingTiming?.endMs,
        }]
        lastAnswer = ''
        pendingTiming = null
        turnStartedAt = Date.now()
      }
      lastQuestion = reply.value
      rounds.value += 1
      turnState.value = 'idle'
    }
    return
  }
  if (type === 'session.created') {
    // 一接通就让面试官先开口，用户听到问题再回答
    socket?.send(JSON.stringify({ type: 'speech_text_buffer.commit', text: openingLine() }))
  }
  if (type.endsWith('transcription.delta')) {
    // 豆包的 delta 是“当前这一句的最新转写”，累积拼接会把同一句重复十几遍
    heard.value = String(event.delta ?? '')
    partialAnswer = heard.value
  } else if (type.endsWith('transcription.completed')) {
    lastAnswer = String(event.transcript ?? event.text ?? heard.value)
    partialAnswer = ''
    heard.value = lastAnswer
    reply.value = ''
    turnState.value = 'heard'
    pendingTiming = { startMs: turnStartedAt || startedAt, endMs: Date.now() }
    turnStartedAt = Date.now()
  } else if (type === 'response.output_text.done') {
    turnState.value = 'speaking'
    reply.value = String(event.text ?? '')
    if (lastAnswer.trim()) {
      turns.value = [...turns.value, {
        question: lastQuestion,
        answer: lastAnswer,
        startMs: pendingTiming?.startMs,
        endMs: pendingTiming?.endMs,
      }]
      lastAnswer = ''
      pendingTiming = null
      turnStartedAt = Date.now()
    }
    lastQuestion = reply.value
    rounds.value += 1
    turnState.value = 'idle'
  } else if (type === 'response.output_audio.delta') {
    playPcm(String(event.delta ?? ''))
  } else if (type === 'error') {
    error.value = JSON.stringify(event.error ?? event).slice(0, 200)
  }
}

/** 形象就位是口型的前提，但不能让它无限期拖住开场，超时就当没有形象继续。 */
function waitAvatar(): Promise<unknown> {
  const opening = avatar.value?.connect() ?? Promise.resolve(false)
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(false), AVATAR_WAIT_MS)
    const done = (ok: boolean) => { window.clearTimeout(timer); resolve(ok) }
    void opening.then(() => done(true), () => done(false))
  })
}

async function start(): Promise<void> {
  if (disposed) return
  closing = false
  status.value = 'connecting'
  error.value = ''
  heard.value = ''
  reply.value = ''
  lastQuestion = openingLine()
  rounds.value = 0
  turnState.value = 'idle'
  micIssue.value = ''
  micLevel.value = 0
  silentSeconds.value = 0
  remaining.value = props.durationMinutes * 60

  const seq = ++sessionSeq

  try {
    // 数字人的口型靠播放音轨转发驱动：先等形象就位再开口，否则开场那句没有音源可转发，
    // 画面里人不动嘴。最多等 9 秒（覆盖 Simli 自身 8 秒建连超时），等不到也照常开始。
    if (isVideo.value) await waitAvatar()
    preparePlayback()
    if (seq !== sessionSeq) return
    const info = await api.get<ApiEnvelope<{ enabled: boolean; voice: string }>>('/voice/status')
    if (disposed || seq !== sessionSeq) return
    if (!info.data.data.enabled) {
      fail('语音服务未配置，请联系管理员')
      return
    }

    if (!(await fetchTicket())) {
      if (seq === sessionSeq) fail('获取语音会话票据失败，请点「重新连接」再试')
      return
    }
    if (disposed || seq !== sessionSeq) return

    socket = new WebSocket(wsUrl())
    // 本地管线回的是裸 PCM 二进制帧；不收成 ArrayBuffer 就没法播放
    socket.binaryType = 'arraybuffer'
    socket.onopen = async () => {
      if (seq !== sessionSeq) return
      if (effectiveEngine.value === 'doubao') {
        reply.value = openingLine() // 保留开场问题供重听和评分使用，不在面试画面展示。
        socket?.send(
          JSON.stringify({
            type: 'session.create',
            session: {
              model: '1.2.6.1',
              instructions: instructions(),
              audio: {
                input: { format: { type: 'pcm', rate: 16000 } },
                output: { format: { type: 'pcm_s16le', rate: 24000 }, voice: info.data.data.voice },
              },
            },
            extension: { asr: { extra: {} }, tts: {}, dialog: {} },
          }),
        )
      }
      status.value = 'live'
      startedAt = Date.now()
      turnStartedAt = startedAt
      beginCountdown()
      // 拿不到麦克风就必须停下来告诉用户原因，否则界面显示“进行中”却永远没有反应
      await startMic()
      if (seq !== sessionSeq) return
      if (micIssue.value) {
        fail(micIssueMessage(micIssue.value))
        return
      }
      silentSeconds.value = 0
    }
    socket.onmessage = (message) => {
      if (seq !== sessionSeq) return
      if (message.data instanceof ArrayBuffer) {
        playPcmBinary(message.data)
        return
      }
      handleEvent(String(message.data))
    }
    socket.onerror = () => {
      if (seq !== sessionSeq) return
      if (!maybeFallback()) fail('连接语音服务失败')
    }
    socket.onclose = (event) => {
      if (closing || seq !== sessionSeq) return
      micOn.value = false
      if (maybeFallback(event.code)) return
      const reasons: Record<number, string> = {
        4001: '语音服务未配置，请联系管理员',
        4003: '语音会话未授权或已断开，请重新开始',
        4004: '语音服务暂时不可用，请稍后重试',
        4005: '语音管线启动失败，可换标准引擎再试',
        4029: '当前语音并发已满，请稍后再试',
      }
      // 服务端 close reason 里带的是可读原因（如“语音管线启动失败：模型未配置”），优先用它
      const reason = (event.reason ?? '').trim()
      fail(reason || reasons[event.code] || '连接已断开，请重新开始面试')
    }
  } catch {
    fail('无法读取语音服务状态')
  }
}

function retry(): void {
  fallbackTried = false
  fallbackNotice.value = ''
  disposeRoomTransport()
  closing = false
  void start()
}

// 权限被拒后浏览器不会再弹框，用户改完站点设置再点这里重试一次
function retryMic(): void {
  showMicGuide.value = false
  micIssue.value = ''
  error.value = ''
  retry()
}

let micWaitTimer = 0

function endMicWaiting(): void {
  if (micWaitTimer) {
    window.clearTimeout(micWaitTimer)
    micWaitTimer = 0
  }
  micWaiting.value = false
}

function maybeFallback(code?: number): boolean {
  // 标准引擎连不上上游时，自动用本地管线重开一次；只尝试一次，避免死循环
  const retryable = code === undefined || [1006, 1011, 4003, 4004, 4005].includes(code)
  if (effectiveEngine.value !== 'doubao' || fallbackTried || !retryable) return false
  fallbackTried = true
  effectiveEngine.value = 'pipeline'
  fallbackNotice.value = '标准引擎暂时不可用，已自动切换到本地管线'
  disposeRoomTransport()
  window.setTimeout(() => { void start() }, 500)
  return true
}

function fail(message: string): void {
  status.value = 'error'
  error.value = message
  disposeRoomTransport()
}

function beginCountdown(): void {
  if (countdown) clearInterval(countdown)
  countdown = setInterval(() => {
    remaining.value -= 1
    // 浏览器把音频上下文挂起时（自动播放策略），用户会以为“没反应”，这里自动恢复
    if (audioContext && audioContext.state === 'suspended') void audioContext.resume()
    resumePlayback()
    if (turnState.value === 'speaking' && playbackExpired()) turnState.value = 'idle'
    silentSeconds.value = micLevel.value > 0.03 || !micOn.value ? 0 : silentSeconds.value + 1
    if (remaining.value <= 0) {
      stopAndReport(true)
    }
  }, 1000)
}

function micIssueKind(reason: unknown): MicIssue {
  const name = (reason as DOMException)?.name ?? ''
  if (!window.isSecureContext) return 'permission'
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'permission'
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError' || name === 'OverconstrainedError') return 'device'
  if (name === 'NotReadableError' || name === 'TrackStartError') return 'busy'
  return 'unsupported'
}

function micIssueMessage(kind: MicIssue): string {
  if (kind === 'permission') return '麦克风权限被拒绝，面试官听不到你说话'
  if (kind === 'device') return '没有找到可用的麦克风：插好设备后点「重新申请权限」'
  if (kind === 'busy') return '麦克风被其他程序占用（会议软件/录音工具），关掉后点「重新申请权限」'
  return '当前页面无法使用麦克风：请用 Chrome / Edge 打开 localhost 或 https 地址'
}

const micSteps = computed<string[]>(() => {
  if (micIssue.value !== 'permission') return []
  return [
    '点浏览器地址栏左侧的图标（锁形或调节滑块）',
    '打开「站点设置」，把「麦克风」' + (isVideo.value ? '和「摄像头」' : '') + '改成「允许」',
    '回到本页点「重新申请权限」；改不动就刷新页面后重新开始',
  ]
})

async function startMic(): Promise<void> {
  const mediaSeq = sessionSeq
  if (!navigator.mediaDevices?.getUserMedia) {
    micIssue.value = 'unsupported'
    return
  }
  micWaiting.value = true
  micWaitTimer = window.setTimeout(() => {
    micWaitTimer = 0
    if (micOn.value) {
      micWaiting.value = false
      return
    }
    endMicWaiting()
    fail('20 秒内没有等到浏览器的授权结果：如果没看到授权弹窗，点「重新申请权限」再试，或按提示改站点设置')
  }, 20000)
  try {
    const acquired = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      ...(isVideo.value ? { video: { width: 1280, height: 720 } } : {}),
    })
    if (mediaSeq !== sessionSeq) {
      acquired.getTracks().forEach((track) => track.stop())
      return
    }
    micStream = acquired
  } catch (reason) {
    endMicWaiting()
    micIssue.value = micIssueKind(reason)
    // 已被拒绝时浏览器不会再弹窗，直接把三步引导摆出来
    if (micIssue.value === 'permission') showMicGuide.value = true
    return
  }
  endMicWaiting()
  if (isVideo.value && preview.value) {
    preview.value.srcObject = micStream
    await preview.value.play().catch(() => undefined)
  }
  if (disposed || mediaSeq !== sessionSeq) return
  audioContext = new AudioContext()
  // Chrome 里新建的上下文可能是 suspended，不 resume 就收不到 onaudioprocess
  if (audioContext.state === 'suspended') await audioContext.resume()
  source = audioContext.createMediaStreamSource(micStream)
  startRecording(micStream, isVideo.value)
  processor = audioContext.createScriptProcessor(1024, 1, 1)
  processor.onaudioprocess = (event) => {
    if (socket?.readyState !== WebSocket.OPEN || !audioContext) return
    const input = event.inputBuffer.getChannelData(0)
    // 电平是用户唯一能立刻看到的“麦克风在工作”的证据
    let peak = 0
    for (let i = 0; i < input.length; i += 8) peak = Math.max(peak, Math.abs(input[i]))
    const now = performance.now()
    if (now - lastLevelAt > 100) {
      micLevel.value = Math.min(1, peak * 4)
      lastLevelAt = now
    }
    const resampled = resample(input, audioContext.sampleRate, 16000)
    const merged = new Float32Array(pending.length + resampled.length)
    merged.set(pending)
    merged.set(resampled, pending.length)
    let offset = 0
    while (merged.length - offset >= 320) {
      const chunk = merged.subarray(offset, offset + 320)
      const pcm = new Int16Array(chunk.length)
      for (let i = 0; i < chunk.length; i += 1) {
        pcm[i] = Math.max(-1, Math.min(1, chunk[i])) * 0x7fff
      }
      if (effectiveEngine.value === 'pipeline') {
        // 本地管线走裸 PCM 二进制帧；标准引擎走 JSON base64
        socket.send(pcm.buffer)
      } else {
        socket.send(JSON.stringify({ type: 'input_audio_buffer.append', audio: toBase64(pcm.buffer) }))
      }
      offset += 320
    }
    pending = merged.slice(offset)
  }
  source.connect(processor)
  processor.connect(audioContext.destination)
  micOn.value = true
}

function resample(input: Float32Array, from: number, to: number): Float32Array {
  if (Math.abs(from - to) < 1) return input
  const ratio = from / to
  const length = Math.floor(input.length / ratio)
  const output = new Float32Array(length)
  for (let i = 0; i < length; i += 1) {
    const position = i * ratio
    const index = Math.floor(position)
    const next = Math.min(index + 1, input.length - 1)
    const weight = position - index
    output[i] = input[index] * (1 - weight) + input[next] * weight
  }
  return output
}

async function stopAndReport(timeUp = false): Promise<void> {
  if (status.value === 'saving') return
  const pendingAnswer = (lastAnswer || partialAnswer).trim()
  const pendingTurns = pendingAnswer
    ? [...turns.value, {
        question: lastQuestion,
        answer: pendingAnswer,
        startMs: pendingTiming?.startMs ?? (turnStartedAt || startedAt),
        endMs: pendingTiming?.endMs ?? Date.now(),
      }]
    : turns.value
  if (!pendingTurns.length) {
    error.value = '还没有可总结的回答；可以继续作答，或直接退出，本次不会保留记录。'
    if (timeUp) fail(error.value)
    return
  }
  emit('finishing')
  if (countdown) { clearInterval(countdown); countdown = null }
  status.value = 'saving'
  reportPending.value = true
  closing = true
  error.value = ''
  try {
    if (!uploadedSessionId.value) {
      socket?.close()
      await finishRecording()
      disposeRoomTransport()
    }
    const completedId = await submitReport({
      sceneId: props.scene?.id ?? '', preparedSessionId: attemptId.value, turns: pendingTurns,
      engine: effectiveEngine.value, channelHint: isVideo.value ? 'VIDEO' : 'VOICE',
      durationSeconds: startedAt ? Math.round((Date.now() - startedAt) / 1000) : 0,
      recording: recordingBlob(),
    })
    reportPending.value = false
    emit('ended', completedId)
  } catch (reason) {
    closing = false
    status.value = 'error'
    error.value = errorMessage(reason)
  } finally {
    disposeRoomTransport()
  }
}

function replayQuestion(): void {
  replaySpeech((reply.value || lastQuestion || openingLine()).trim())
}

function interrupt(): void {
  if (effectiveEngine.value === 'pipeline') {
    socket?.send(new ArrayBuffer(0))
  } else {
    socket?.send(JSON.stringify({ type: 'response.cancel' }))
  }
  stopPlayback()
  turnState.value = 'idle'
  reply.value = ''
}



// ---- 画中画（仅视频模式）：拖动 / 四角吸附 / 位置与尺寸记忆 ----
const SELF_POS_KEY = 'yanjie:selfPreviewPos'
const SELF_PAD = 8
const SELF_SNAP = 80
const SELF_NUDGE = 10
const SELF_WIDTHS = { small: 180, large: 280 } as const
type SelfSizeKey = keyof typeof SELF_WIDTHS
type SelfBounds = { rect: DOMRect; width: number; height: number; minX: number; maxX: number; minY: number; maxY: number }

const selfPreview = useTemplateRef<HTMLElement>('selfPreview')
const selfSize = shallowRef<SelfSizeKey>('small')
const selfDragging = shallowRef(false)
// 首次进入房间给一句可见提示，之后不再打扰
const SELF_HINT_KEY = 'yanjie:selfPreviewHintSeen'
const selfHint = shallowRef(false)
let selfHintTimer: ReturnType<typeof setTimeout> | null = null

function dismissSelfHint(): void {
  selfHint.value = false
  if (selfHintTimer) { clearTimeout(selfHintTimer); selfHintTimer = null }
  try { localStorage.setItem(SELF_HINT_KEY, '1') } catch { /* 隐私模式忽略 */ }
}
type SelfLayout = { x: number; y: number; width: number; ready: boolean }
const selfLayout = shallowRef<SelfLayout>({ x: 0, y: 0, width: SELF_WIDTHS.small, ready: false })
// 归一化坐标（小窗左上角占舞台宽高的比例）是位置的事实来源：窗口缩放、进出沉浸都按它重算再夹取
let selfRatio: { x: number; y: number } | null = null
let selfDrag: { pointerId: number; dx: number; dy: number } | null = null
let selfObserver: ResizeObserver | null = null

function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(Math.max(min, max), value))
}

function selfStage(): HTMLElement | null {
  return selfPreview.value?.parentElement ?? null
}

// 舞台与 .video-toolbar / .room-controls 是同级流式布局，正常不重叠；
// 小视口下若真被压到舞台上，就把相交高度计入安全边距，保证遮不住工具栏与控制条。
function selfInsets(rect: DOMRect): { top: number; bottom: number } {
  const intrude = (selector: string): number => {
    const panel = roomElement.value?.querySelector(selector)
    if (!panel) return 0
    const box = panel.getBoundingClientRect()
    return Math.max(0, Math.min(box.bottom, rect.bottom) - Math.max(box.top, rect.top))
  }
  return { top: SELF_PAD + intrude('.video-toolbar'), bottom: SELF_PAD + intrude('.room-controls') }
}

function measureSelf(): SelfBounds | null {
  const stage = selfStage()
  if (!stage) return null
  const rect = stage.getBoundingClientRect()
  if (rect.width < 40 || rect.height < 40) return null
  const insets = selfInsets(rect)
  const width = Math.max(96, Math.min(SELF_WIDTHS[selfSize.value], rect.width - SELF_PAD * 2))
  const height = Math.round((width * 10) / 16)
  return {
    rect,
    width,
    height,
    minX: SELF_PAD,
    minY: insets.top,
    maxX: Math.max(SELF_PAD, rect.width - width - SELF_PAD),
    maxY: Math.max(insets.top, rect.height - height - insets.bottom),
  }
}

function layoutSelf(): void {
  const bounds = measureSelf()
  if (!bounds) return
  const ratio = selfRatio ?? { x: bounds.maxX / bounds.rect.width, y: bounds.maxY / bounds.rect.height }
  selfRatio = ratio
  selfLayout.value = {
    x: clampNumber(ratio.x * bounds.rect.width, bounds.minX, bounds.maxX),
    y: clampNumber(ratio.y * bounds.rect.height, bounds.minY, bounds.maxY),
    width: bounds.width,
    ready: true,
  }
}

function placeSelf(x: number, y: number, bounds: SelfBounds): void {
  selfLayout.value = { x, y, width: bounds.width, ready: true }
  selfRatio = { x: x / bounds.rect.width, y: y / bounds.rect.height }
}

function readSelfPref(): { x: number; y: number; size: SelfSizeKey } | null {
  try {
    const raw = localStorage.getItem(SELF_POS_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { x?: unknown; y?: unknown; size?: unknown }
    const x = Number(parsed.x)
    const y = Number(parsed.y)
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null
    return { x: clampNumber(x, 0, 1), y: clampNumber(y, 0, 1), size: parsed.size === 'large' ? 'large' : 'small' }
  } catch { return null }
}

function persistSelf(): void {
  try {
    if (!selfRatio) return
    localStorage.setItem(SELF_POS_KEY, JSON.stringify({
      x: Number(selfRatio.x.toFixed(4)),
      y: Number(selfRatio.y.toFixed(4)),
      size: selfSize.value,
    }))
  } catch { /* 隐私模式或配额满：位置记忆是可降级能力，不影响面试 */ }
}

function onSelfPointerDown(event: PointerEvent): void {
  if (event.button !== 0 || !event.isPrimary) return
  if ((event.target as HTMLElement | null)?.closest('.self-resize')) return
  if (selfHint.value) dismissSelfHint()
  const preview = selfPreview.value
  if (!preview || !measureSelf()) return
  const box = preview.getBoundingClientRect()
  selfDrag = { pointerId: event.pointerId, dx: event.clientX - box.left, dy: event.clientY - box.top }
  selfDragging.value = true
  preview.setPointerCapture(event.pointerId)
  event.preventDefault()
}

function onSelfPointerMove(event: PointerEvent): void {
  if (!selfDrag || event.pointerId !== selfDrag.pointerId) return
  const bounds = measureSelf()
  if (!bounds) return
  placeSelf(
    clampNumber(event.clientX - bounds.rect.left - selfDrag.dx, bounds.minX, bounds.maxX),
    clampNumber(event.clientY - bounds.rect.top - selfDrag.dy, bounds.minY, bounds.maxY),
    bounds,
  )
  event.preventDefault()
}

function onSelfPointerUp(event: PointerEvent): void {
  if (!selfDrag || event.pointerId !== selfDrag.pointerId) return
  const preview = selfPreview.value
  selfDrag = null
  selfDragging.value = false
  if (preview?.hasPointerCapture(event.pointerId)) preview.releasePointerCapture(event.pointerId)
  snapSelf()
}

// 松手吸附到最近的角；离角超过阈值就停在松手处，避免被硬拽到对角
function snapSelf(): void {
  const bounds = measureSelf()
  if (!bounds) return
  const corners = [
    { x: bounds.minX, y: bounds.minY },
    { x: bounds.maxX, y: bounds.minY },
    { x: bounds.minX, y: bounds.maxY },
    { x: bounds.maxX, y: bounds.maxY },
  ]
  let nearest = { x: bounds.maxX, y: bounds.maxY }
  let distance = Number.POSITIVE_INFINITY
  for (const corner of corners) {
    const next = Math.hypot(corner.x - selfLayout.value.x, corner.y - selfLayout.value.y)
    if (next < distance) { distance = next; nearest = corner }
  }
  if (distance <= SELF_SNAP) placeSelf(nearest.x, nearest.y, bounds)
  persistSelf()
}

function resetSelf(): void {
  const bounds = measureSelf()
  if (!bounds) return
  placeSelf(bounds.maxX, bounds.maxY, bounds)
  persistSelf()
}

function toggleSelfSize(): void {
  selfSize.value = selfSize.value === 'small' ? 'large' : 'small'
  layoutSelf()
  persistSelf()
}

function onSelfKeydown(event: KeyboardEvent): void {
  const bounds = measureSelf()
  if (!bounds) return
  let dx = 0
  let dy = 0
  if (event.key === 'ArrowLeft') dx = -SELF_NUDGE
  else if (event.key === 'ArrowRight') dx = SELF_NUDGE
  else if (event.key === 'ArrowUp') dy = -SELF_NUDGE
  else if (event.key === 'ArrowDown') dy = SELF_NUDGE
  else return
  event.preventDefault()
  event.stopPropagation()
  placeSelf(
    clampNumber(selfLayout.value.x + dx, bounds.minX, bounds.maxX),
    clampNumber(selfLayout.value.y + dy, bounds.minY, bounds.maxY),
    bounds,
  )
  persistSelf()
}

function watchSelfStage(): void {
  const stage = selfStage()
  if (!stage || typeof ResizeObserver === 'undefined') return
  selfObserver?.disconnect()
  selfObserver = new ResizeObserver(() => layoutSelf())
  selfObserver.observe(stage)
}

// 进出沉浸时 Teleport 会把房间搬去 body，等布局稳定再按比例重新夹取
watch(immersive, () => {
  if (!isVideo.value) return
  void nextTick(() => { layoutSelf(); watchSelfStage() })
});

function onRoomKeydown(event: KeyboardEvent): void {
  if (!isVideo.value) return
  if (event.metaKey || event.ctrlKey || event.altKey) return
  if (event.key === 's' || event.key === 'S') {
    event.preventDefault()
    toggleSelfSize()
    return
  }
  if (!immersive.value) return
  if (event.key === 'Escape') immersive.value = false
  if (event.key !== 'Tab') return
  const controls = Array.from(roomElement.value?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href]') ?? [])
    .filter((element) => element.getClientRects().length)
  const last = controls[controls.length - 1]
  const target = event.shiftKey ? last : controls[0]
  const boundary = event.shiftKey ? controls[0] : last
  if (document.activeElement === boundary || document.activeElement === roomElement.value) {
    event.preventDefault()
    target?.focus()
  }
}

function disposeRoomTransport(): void {
  sessionSeq++
  endMicWaiting()
  if (countdown) { clearInterval(countdown); countdown = null }
  stopRecording()
  processor?.disconnect()
  source?.disconnect()
  void audioContext?.close()
  micStream?.getTracks().forEach((track) => track.stop())
  processor = null
  source = null
  audioContext = null
  disposePlayback()
  void avatar.value?.disconnect()
  micStream = null
  micOn.value = false
  socket?.close()
  socket = null
  closing = true
}

onMounted(async () => {
  if (isVideo.value) {
    roomElement.value?.focus({ preventScroll: true })
    const saved = readSelfPref()
    if (saved) {
      selfRatio = { x: saved.x, y: saved.y }
      selfSize.value = saved.size
    }
    void nextTick(() => { layoutSelf(); watchSelfStage() })
    let seen = false
    try { seen = localStorage.getItem(SELF_HINT_KEY) === '1' } catch { seen = false }
    if (!seen) {
      selfHint.value = true
      selfHintTimer = setTimeout(dismissSelfHint, 6000)
    }
  }
  try {
    if (!attemptId.value) {
      const form = new FormData()
      form.append('sceneId', props.scene?.id ?? '')
      form.append('channel', props.captureMode.toUpperCase())
      form.append('evidenceDriven', 'true')
      form.append('depth', props.depth ?? 'STANDARD')
      form.append('duration', String(props.durationMinutes))
      const prepared = (await api.post<ApiEnvelope<{ id: string }>>('/training-sessions/prepare', form)).data.data.id
      if (disposed) {
        await api.post(`/training-sessions/${prepared}/discard`)
        return
      }
      attemptId.value = prepared
    }
    emit('prepared', attemptId.value)
    interviewContext.value = (await api.get<ApiEnvelope<{ instructions: string; openingLine: string; minimumRounds?: number }>>(`/training-sessions/${attemptId.value}/interview-context`)).data.data
    if (disposed) return
    await start()
  } catch { fail('面试准备失败，请返回场景重新开始') }
})
// 一轮都没产生的空场次不该在训练记录里留痕：没人答题就直接 discard 掉占位会话
async function discardEmptyAttempt(): Promise<void> {
  const id = attemptId.value
  if (!id || attemptDiscarded || rounds.value > 0 || turns.value.length) return
  if (status.value === 'saving' || uploadedSessionId.value) return
  attemptDiscarded = true
  try { await api.post(`/training-sessions/${id}/discard`) } catch { /* 退出清理是尽力而为，后端还有兜底脚本 */ }
}

onBeforeUnmount(() => {
  disposed = true
  selfObserver?.disconnect()
  disposeRoomTransport()
  void discardEmptyAttempt()
})
</script>

<template>
  <Teleport to="body" :disabled="!isVideo || !immersive">
  <section
    ref="roomElement"
    class="room"
    :class="{ 'room-video': isVideo, 'room-immersive': isVideo && immersive }"
    :role="isVideo && immersive ? 'dialog' : undefined"
    :aria-modal="isVideo && immersive ? true : undefined"
    :aria-label="isVideo ? '视频面试室' : '语音面试室'"
    tabindex="-1"
    @keydown="onRoomKeydown"
  >
    <header v-if="isVideo" class="video-toolbar">
      <span class="call-label"><i :class="{ connected: status === 'live' }" aria-hidden="true" />{{ statusLabel }}</span>
      <span class="room-title">{{ scene?.title ?? '模拟面试' }}</span>
      <button class="immersion-toggle" type="button" :aria-pressed="immersive" @click="immersive = !immersive">
        <component :is="immersive ? Minimize2 : Maximize2" :size="15" aria-hidden="true" />
        {{ immersive ? '退出沉浸' : '沉浸模式' }}
      </button>
    </header>
    <div class="room-stage">
      <template v-if="isVideo">
        <AvatarPresenter ref="avatar" :active="status === 'live' || status === 'connecting'" :speaking="interviewerSpeaking" :listening="interviewerListening" />
        <div class="room-overlay">
          <span class="badge">模拟面试官</span>
          <span class="clock" aria-label="剩余时间">{{ timeLabel }}</span>
        </div>
        <div class="interviewer">
          <span class="speaking-indicator" :class="{ active: interviewerSpeaking }" aria-hidden="true"><i v-for="n in 4" :key="n" :style="{ animationDelay: `${n * 90}ms` }" /></span>
          <div>
            <strong>{{ scene?.roleName ?? '面试官' }}</strong>
            <small role="status">{{ liveStatus }}</small>
          </div>
        </div>
        <div
          ref="selfPreview"
          class="self-preview"
          :class="{ hearing: interviewerListening && micLevel > 0.03, large: selfSize === 'large', dragging: selfDragging, positioned: selfLayout.ready }"
          :style="selfLayout.ready ? { left: `${selfLayout.x}px`, top: `${selfLayout.y}px`, width: `${selfLayout.width}px` } : undefined"
          role="group"
          aria-label="我的摄像头画面，可拖动，双击复位，方向键微调，S 键切换大小"
          title="双击复位"
          tabindex="0"
          @pointerdown="onSelfPointerDown"
          @pointermove="onSelfPointerMove"
          @pointerup="onSelfPointerUp"
          @pointercancel="onSelfPointerUp"
          @dblclick="resetSelf"
          @keydown="onSelfKeydown"
        >
          <video ref="preview" class="room-self" muted aria-label="我的摄像头画面" />
          <span class="self-label"><Mic :size="12" aria-hidden="true" />我</span>
          <span v-if="selfHint" class="self-hint" aria-hidden="true">拖动可移动 · 双击复位</span>
          <span class="self-meter" aria-hidden="true"><i :style="{ width: `${Math.max(3, Math.round(micLevel * 100))}%` }" /></span>
          <button
            class="self-resize"
            type="button"
            :aria-label="selfSize === 'small' ? '放大我的画面' : '缩小我的画面'"
            :title="selfSize === 'small' ? '放大我的画面（S）' : '缩小我的画面（S）'"
            @pointerdown.stop
            @click.stop="toggleSelfSize"
          >
            <component :is="selfSize === 'small' ? Maximize2 : Minimize2" :size="13" aria-hidden="true" />
          </button>
        </div>
      </template>
      <template v-else>
        <div class="voice-stage">
          <span class="voice-avatar">{{ (scene?.roleName ?? '面')[0] }}</span>
          <strong>{{ scene?.roleName ?? 'AI 面试官' }}</strong>
          <p>{{ statusLabel }} · 剩余 {{ timeLabel }}</p>
          <p class="voice-status" :class="{ speaking: turnState === 'speaking', hearing: micLevel > 0.03 }">{{ liveStatus }}</p>
          <div class="voice-meter" :class="{ hot: micLevel > 0.03 }" aria-hidden="true">
            <i :style="{ width: `${Math.max(3, Math.round(micLevel * 100))}%` }" />
          </div>
          <div class="wave" :class="{ active: status === 'live' }" aria-hidden="true">
            <i v-for="n in 28" :key="n" :style="{ animationDelay: `${n * 35}ms` }" />
          </div>
        </div>
      </template>
    </div>

    <p v-if="!isVideo" class="voice-note">语音面试不显示文字气泡；转写只在后台用于生成评分报告。</p>

    <p v-if="fallbackNotice" class="fallback">{{ fallbackNotice }}</p>
    <p v-if="exitError" class="room-error" role="alert">{{ exitError }}</p>

    <div v-if="error" class="room-error-block" role="alert">
      <p class="room-error">{{ error }}</p>
      <ol v-if="micSteps.length && !showMicGuide" class="room-steps">
        <li v-for="(step, index) in micSteps" :key="index">{{ step }}</li>
      </ol>
      <div class="room-fix">
        <button v-if="micIssue" class="button secondary" type="button" @click="retryMic">
          {{ micIssue === 'permission' ? '重新申请麦克风权限' : '重新申请权限' }}
        </button>
        <button v-else-if="reportPending" class="button secondary" type="button" @click="stopAndReport(false)">重试生成报告</button>
        <button v-else class="button secondary" type="button" @click="retry">重新连接</button>
        <button v-if="isVideo" class="button secondary" type="button" @click="emit('switchVoice')">改用语音面试</button>
      </div>
    </div>

    <div class="room-controls">
      <RouterLink class="button secondary" to="/scenes">{{ reportPending ? '返回场景' : '直接退出' }}</RouterLink>
      <button class="button secondary" type="button" :disabled="status !== 'live'" @click="replayQuestion"><RotateCcw v-if="isVideo" :size="15" aria-hidden="true" />重听问题</button>
      <button class="button secondary" type="button" :disabled="status !== 'live' || (!reply && !interviewerSpeaking)" @click="interrupt"><Hand v-if="isVideo" :size="15" aria-hidden="true" />打断</button>
      <button class="button end" type="button" :disabled="status === 'saving' || status === 'connecting'" @click="stopAndReport(false)">
        <PhoneOff :size="15" :stroke-width="1.8" aria-hidden="true" />
        {{ status === 'saving' ? '正在生成报告…' : '结束面试' }}
      </button>
      <span class="mic-state"><Mic :size="13" :stroke-width="1.8" aria-hidden="true" />{{ micOn ? '麦克风已开启' : '等待麦克风' }} · 已进行 {{ rounds }} 轮</span>
    </div>
    <p class="mic-state">{{ reportPending ? '本次面试已结束，报告会保留在训练记录中。' : '直接退出不保留记录；结束面试按已有作答生成总结。' }}</p>

    <PermissionDialog v-if="micWaiting" variant="waiting" :devices="micDevices" />
    <PermissionDialog v-if="showMicGuide" variant="denied" :devices="micDevices" @retry="retryMic" @close="showMicGuide = false" />
  </section>
  </Teleport>
</template>

<style scoped>
.room { display: grid; gap: 16px; padding: 18px; border: 1px solid var(--border); border-radius: 16px; background: var(--card); }
.room-stage { position: relative; border-radius: 14px; overflow: hidden; background: #0b0b0e; }
.room-video { gap: 14px; padding: 18px; background: #192631; color: #edf3f7; border-color: #2e414f; }
.room-immersive { position: fixed; inset: 0; z-index: 60; display: flex; flex-direction: column; min-width: 1200px; border: 0; border-radius: 0; padding: 18px 24px; }
.room-video:focus { outline: none; }
.video-toolbar { display: grid; grid-template-columns: 1fr minmax(0, 1fr) 1fr; align-items: center; gap: 16px; min-height: 34px; }
.call-label { display: flex; align-items: center; gap: 8px; color: #c0cfda; font-size: 12px; }
.call-label i { width: 6px; height: 6px; border-radius: 50%; background: #d5bc86; }
.call-label i.connected { background: #a7d2bd; }
.room-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: center; font-size: 13px; color: #dce7ed; }
.immersion-toggle { justify-self: end; display: inline-flex; align-items: center; gap: 7px; padding: 8px 10px; border: 1px solid #43525f; border-radius: 8px; background: transparent; color: #dce7ed; font: inherit; font-size: 12px; cursor: pointer; }
.immersion-toggle:hover { background: #2e414f; }
.room-video .room-stage { aspect-ratio: 16 / 9; background: #e5edf3; }
.room-immersive .room-stage { flex: 1; min-height: 0; aspect-ratio: auto; }
.self-preview { position: absolute; right: 22px; bottom: 22px; width: 180px; aspect-ratio: 16 / 10; border: 2px solid #f6fafb; border-radius: 12px; overflow: hidden; background: #263744; box-shadow: 0 6px 24px #14273330; transition: border-color .2s, box-shadow .2s, width .18s; cursor: grab; touch-action: none; user-select: none; }
.self-preview.positioned { right: auto; bottom: auto; }
.self-preview.large { width: 280px; }
.self-preview:focus-visible { outline: 2px solid #b6d7ec; outline-offset: 3px; }
.self-preview.dragging { z-index: 3; cursor: grabbing; box-shadow: 0 16px 38px #0b1c2459; transform: translateY(-2px); }
.self-preview.hearing { border-color: #8ac7a4; }
.self-hint { position: absolute; left: 50%; bottom: 34px; transform: translateX(-50%); padding: 2px 8px; border-radius: 999px; background: #0b1a24cc; color: #eaf3f7; font-size: 10.5px; line-height: 1.6; white-space: nowrap; pointer-events: none; }
.self-resize { position: absolute; top: 6px; right: 6px; display: grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 0; border-radius: 6px; background: #192631b3; color: #f6fafb; cursor: pointer; }
.self-resize:hover { background: #192631e6; }
.self-resize:focus-visible { outline: 2px solid #b6d7ec; outline-offset: 2px; }
.room-self { display: block; width: 100%; height: 100%; object-fit: cover; transform: scaleX(-1); }
.self-label { position: absolute; left: 9px; bottom: 9px; display: flex; align-items: center; gap: 5px; padding: 3px 7px; border-radius: 5px; color: #fff; background: #192631aa; font-size: 11px; }
.self-meter { position: absolute; inset: auto 0 0; height: 3px; background: #ffffff30; }
.self-meter i { display: block; height: 100%; background: #9ad0b2; transition: width .12s linear; }
.room-overlay { position: absolute; inset: 12px 14px auto; display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #fff; }
.badge { padding: 5px 12px; border-radius: 999px; background: rgba(0, 0, 0, .5); font-size: 11.5px; backdrop-filter: blur(6px); }
.clock { padding: 5px 12px; border-radius: 999px; background: rgba(0, 0, 0, .5); font-variant-numeric: tabular-nums; font-size: 12px; }
.interviewer { position: absolute; left: 22px; bottom: 22px; display: flex; align-items: center; gap: 12px; max-width: calc(100% - 330px); padding: 12px 16px; border: 1px solid #ffffff26; border-radius: 12px; background: #192631d9; color: #fff; backdrop-filter: blur(8px); }
.interviewer strong { display: block; font-size: 13px; }
.interviewer small { display: block; margin-top: 4px; color: #d5e1e8; font-size: 11px; }
.speaking-indicator { display: flex; align-items: center; gap: 3px; width: 24px; height: 26px; }
.speaking-indicator i { width: 3px; height: 5px; border-radius: 3px; background: #c7d9e1; }
.speaking-indicator.active i { background: #a7d2bd; animation: speaking .6s ease-in-out infinite alternate; }
@keyframes speaking { to { height: 22px; } }
.voice-stage { display: grid; justify-items: center; gap: 8px; padding: 44px 20px 30px; background: radial-gradient(circle at 50% 20%, rgba(164, 70, 31, .25), transparent 60%), #0b0b0e; color: #fff; }
.voice-avatar { display: grid; place-items: center; width: 74px; height: 74px; border-radius: 50%; background: var(--accent); font-size: 30px; }
.voice-stage strong { font-size: 18px; }
.voice-stage p { margin: 0; color: rgba(255, 255, 255, .65); font-size: 12px; }
.wave { display: flex; align-items: center; gap: 4px; height: 56px; margin-top: 8px; }
.wave i { width: 3px; height: 10px; border-radius: 99px; background: rgba(255, 255, 255, .35); }
.wave.active i { background: var(--accent); animation: pulse 1.1s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { height: 8px; } 50% { height: 34px; } }
@media (prefers-reduced-motion: reduce) { .wave.active i { animation: none; height: 18px; } }
.voice-status { font-size: 13px !important; color: rgba(255, 255, 255, .82) !important; }
.voice-status.hearing { color: #9be3b4 !important; }
.voice-status.speaking { color: var(--accent) !important; }
.voice-meter { width: 190px; height: 4px; border-radius: 99px; background: rgba(255, 255, 255, .16); overflow: hidden; }
.voice-meter i { display: block; height: 100%; background: var(--accent); transition: width .1s linear; }
.voice-meter.hot i { background: #48c97a; }
.voice-note { margin: 0; color: var(--text-3); font-size: 12px; }
.room-error-block { display: grid; gap: 10px; padding: 14px 16px; border: 1px solid var(--danger); border-radius: 12px; background: var(--bg-2); }
.room-error { margin: 0; color: var(--danger); font-size: 12.5px; }
.room-steps { margin: 0; padding-left: 18px; color: var(--text-2); font-size: 12.5px; line-height: 1.9; }
.room-fix { display: flex; gap: 10px; flex-wrap: wrap; }
.fallback { margin: 0; color: var(--accent-strong); font-size: 12px; }
.room-controls { display: flex; align-items: center; gap: 10px; }
.button.end { background: var(--accent); border-color: var(--accent); color: #fff; display: inline-flex; align-items: center; gap: 6px; }
.mic-state { display: inline-flex; align-items: center; gap: 5px; margin-left: auto; color: var(--text-3); font-size: 11.5px; }
.room-video .room-controls { padding: 3px 0; }
.room-video .room-controls .button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 43px; padding: 0 19px; border-radius: 10px; }
.room-video .button.secondary { border-color: #43525f; background: #243540; color: #edf3f7; }
.room-video .button.secondary:hover:not(:disabled) { background: #344b5a; }
.room-video .button.end { margin-left: 5px; border-color: #b64f4c; background: #b64f4c; }
.room-video .mic-state { color: #bdccd6; }
.room-video .room-error-block { flex-shrink: 0; background: #fff4ef; color: #752e26; }
.room-video .fallback { color: #e6c695; }
.room-video button:focus-visible { outline: 2px solid #b6d7ec; outline-offset: 4px; }
@media (prefers-reduced-motion: reduce) {
  .speaking-indicator.active i { animation: none; height: 14px; }
  .self-preview, .self-meter i { transition: none; }
}
</style>
