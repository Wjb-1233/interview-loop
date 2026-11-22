import { shallowRef } from 'vue'

import { authorizedFetch } from '@/lib/api'

interface AvatarAudioTarget {
  observeAudio(analyser: AnalyserNode | null): void
  finishAudio(): void
  /** 数字人自己出声（回流带音轨）时为真：本地 TTS 只送不播，否则两路声音差约一秒。 */
  ownsAudio?: () => boolean
  /** 重听只能退回浏览器朗读时，向用户说明这一遍不驱动数字人口型。 */
  noticeReplayFallback?: (message: string) => void
}

/** 重听走浏览器 TTS 时口型拿不到音源，必须明说，不能假装在动。 */
const REPLAY_UNSYNCED_NOTICE = '本次重听不驱动数字人口型'

/** 数字人出声时，回流的末字比本地缓冲晚到约一秒：收尾要等这么久才算真说完。 */
const REMOTE_TAIL_MS = 1000

/** Owns playback resources only. Connection and upload lifecycle belongs to the room. */
export function useInterviewPlayback(avatar: () => AvatarAudioTarget | null, onSpeaking: () => void, onFinished: () => void) {
  const speakerActive = shallowRef(false)
  const replayActive = shallowRef(false)
  let context: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  const nodes = new Set<AudioBufferSourceNode>()
  let replay: SpeechSynthesisUtterance | null = null
  let playbackAt = 0
  /** 本地是否直连扬声器。数字人接管出声后断开这条连接，音源仍照常流向数字人做口型。 */
  let localAudible = true
  let finishTimer = 0
  // 每次 stopPlayback 自增：在途的重听请求回来后发现自己过期就直接丢弃
  let replayToken = 0

  function playback(): AudioContext {
    if (!context) {
      context = new AudioContext({ sampleRate: 24000 })
      analyser = context.createAnalyser()
      analyser.fftSize = 256
      analyser.connect(context.destination)
    }
    if (context.state === 'suspended') void context.resume()
    return context
  }

  /** 数字人出声时掐掉本地扬声器这条路（AnalyserNode 的另一路仍喂口型），否则同一句话说两遍。 */
  function routeToAvatar(remote: boolean): void {
    const ctx = context
    if (!ctx || !analyser) return
    if (localAudible === !remote) return
    localAudible = !remote
    try {
      if (localAudible) analyser.connect(ctx.destination)
      else analyser.disconnect(ctx.destination)
    } catch { /* 本来就没连/已断开 */ }
  }

  function clearFinish(): void {
    if (finishTimer) { window.clearTimeout(finishTimer); finishTimer = 0 }
  }

  /** 数字人出声时最后一句还在路上，收尾要延后一个回流延迟，避免提前静音掐掉尾音。 */
  function settle(): void {
    clearFinish()
    const tail = localAudible ? 0 : REMOTE_TAIL_MS
    if (!tail) {
      speakerActive.value = false
      replayActive.value = false
      onFinished()
      return
    }
    finishTimer = window.setTimeout(() => {
      finishTimer = 0
      speakerActive.value = false
      replayActive.value = false
      onFinished()
    }, tail)
  }

  /**
   * 所有出声的音频都从这里进：接到同一个 AnalyserNode，
   * 数字人（Simli）与 3D 口型拿到的就是这一路，重听和正式播报没有分叉。
   */
  function queueBuffer(buffer: AudioBuffer, isReplay = false): void {
    const ctx = playback()
    routeToAvatar(avatar()?.ownsAudio?.() ?? false)
    avatar()?.observeAudio(analyser)
    const node = ctx.createBufferSource()
    node.buffer = buffer
    node.connect(analyser ?? ctx.destination)
    nodes.add(node)
    speakerActive.value = true
    if (isReplay) replayActive.value = true
    node.onended = () => {
      nodes.delete(node)
      if (!nodes.size) settle()
      node.disconnect()
    }
    playbackAt = Math.max(playbackAt, ctx.currentTime + 0.05)
    node.start(playbackAt)
    playbackAt += buffer.duration
    onSpeaking()
  }

  /**
   * 开口之前先把音源备好：数字人的口型靠这条 AnalyserNode 转发，
   * 等第一帧音频才建 tap 的话，先到的那句（开场提问）没有音源可转，只剩无声画面。
   */
  function preparePlayback(): void {
    const ctx = playback()
    routeToAvatar(avatar()?.ownsAudio?.() ?? false)
    if (analyser) avatar()?.observeAudio(analyser)
    if (ctx.state === 'suspended') void ctx.resume()
  }

  function queuePcm(samples: Float32Array): void {
    if (!samples.length) return
    const ctx = playback()
    const buffer = ctx.createBuffer(1, samples.length, 24000)
    buffer.copyToChannel(samples, 0)
    queueBuffer(buffer)
  }

  function toSamples(data: Uint8Array): Float32Array {
    const view = new DataView(data.buffer, data.byteOffset, data.byteLength)
    const samples = new Float32Array(Math.floor(data.byteLength / 2))
    for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i * 2, true) / 32768
    return samples
  }

  function playPcm(base64: string): void {
    const binary = atob(base64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    queuePcm(toSamples(bytes))
  }
  function playPcmBinary(data: ArrayBuffer): void { queuePcm(toSamples(new Uint8Array(data))) }

  /** 重听取后端 TTS 预览的音频（与正式播报同一个合成器），解出 AudioBuffer 后走同一条播放链路。 */
  async function loadReplayBuffer(text: string, token: number): Promise<AudioBuffer | null> {
    try {
      const response = await authorizedFetch('/scripts/preview', {
        method: 'POST',
        body: JSON.stringify({ text }),
      })
      if (!response.ok) return null
      const payload = await response.json() as { data?: { url?: string } }
      const url = payload?.data?.url
      if (!url) return null
      const audio = await fetch(url, { credentials: 'include' })
      if (!audio.ok) return null
      const bytes = await audio.arrayBuffer()
      // 期间房间已关闭/被打断：别再为这遍重听新建 AudioContext
      if (token !== replayToken) return null
      const buffer = await playback().decodeAudioData(bytes)
      return buffer && buffer.duration > 0 ? buffer : null
    } catch { return null }
  }

  function stopPlayback(): void {
    replayToken += 1
    clearFinish()
    avatar()?.finishAudio()
    replay = null
    replayActive.value = false
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    for (const node of nodes) {
      node.onended = null
      try { node.stop() } catch { /* Already ended. */ }
      node.disconnect()
    }
    nodes.clear()
    speakerActive.value = false
    playbackAt = 0
  }

  /** 只有 TTS 预览不可用才退回浏览器朗读，并明说这一遍不驱动口型。 */
  function speakWithBrowser(text: string): void {
    avatar()?.noticeReplayFallback?.(REPLAY_UNSYNCED_NOTICE)
    if (!('speechSynthesis' in window)) return
    const utterance = new SpeechSynthesisUtterance(text)
    replay = utterance
    utterance.lang = 'zh-CN'
    utterance.rate = 0.92
    utterance.onstart = () => { if (replay === utterance) replayActive.value = true }
    const done = () => { if (replay === utterance) { replayActive.value = false; replay = null } }
    utterance.onend = done
    utterance.onerror = done
    window.speechSynthesis.speak(utterance)
  }

  async function replaySpeech(text: string): Promise<void> {
    if (!text) return
    stopPlayback()
    const token = replayToken
    const buffer = await loadReplayBuffer(text, token)
    // 期间被打断/又点了重听：这遍直接作废，不叠音
    if (token !== replayToken) return
    if (buffer) { queueBuffer(buffer, true); return }
    speakWithBrowser(text)
  }

  function disposePlayback(): void {
    stopPlayback()
    void context?.close()
    context = null
    analyser = null
  }
  function resumePlayback(): void { if (context?.state === 'suspended') void context.resume() }
  return { speakerActive, replayActive, playPcm, playPcmBinary, replaySpeech, stopPlayback, disposePlayback, resumePlayback, preparePlayback,
    playbackExpired: () => playbackAt <= (context?.currentTime ?? 0) }
}
