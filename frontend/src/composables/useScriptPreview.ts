import { onBeforeUnmount, shallowRef } from 'vue'

import { api, errorMessage } from '@/lib/api'
import type { ApiEnvelope, ScriptVersion } from '@/lib/types'

export function useScriptPreview(setError: (message: string) => void) {
  const previewingId = shallowRef('')
  const playingId = shallowRef('')
  let audio: HTMLAudioElement | null = null
  let controller: AbortController | null = null

  function stopAudio() {
    if (audio) {
      audio.onended = null
      audio.onerror = null
      audio.pause()
      audio = null
    }
    playingId.value = ''
  }

  async function playPreview(version: ScriptVersion): Promise<void> {
    if (playingId.value === version.id) { stopAudio(); return }
    if (previewingId.value) return
    stopAudio()
    setError('')
    previewingId.value = version.id
    const request = new AbortController()
    controller = request
    try {
      const response = await api.post<ApiEnvelope<{ url: string }>>('/scripts/preview', { text: version.content }, { signal: request.signal })
      if (request.signal.aborted) return
      audio = new Audio(response.data.data.url)
      audio.onended = stopAudio
      audio.onerror = () => { stopAudio(); setError('试听音频加载失败，请稍后重试。') }
      try {
        await audio.play()
        playingId.value = version.id
      } catch {
        stopAudio()
        setError('试听播放失败，请检查浏览器声音权限后重试。')
      }
    } catch (reason) {
      if (!request.signal.aborted) setError(errorMessage(reason))
    } finally {
      previewingId.value = ''
      controller = null
    }
  }

  onBeforeUnmount(() => { controller?.abort(); stopAudio() })
  return { previewingId, playingId, playPreview }
}
