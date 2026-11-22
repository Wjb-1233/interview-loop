import { shallowRef } from 'vue'
import { api, MODEL_REQUEST_TIMEOUT_MS } from '@/lib/api'
import type { ApiEnvelope } from '@/lib/types'

export interface InterviewSubmission {
  sceneId: string
  preparedSessionId: string
  turns: Array<{ question: string; answer: string; startMs?: number; endMs?: number }>
  engine: string
  channelHint: 'VOICE' | 'VIDEO'
  durationSeconds: number
  recording: Blob | null
}

/** An uploaded answer set is reused when report generation must be retried. */
export function useInterviewSubmission() {
  const uploadedSessionId = shallowRef('')
  const submissionStage = shallowRef<'notUploaded' | 'uploaded' | 'reportReady'>('notUploaded')
  async function submitReport(input: InterviewSubmission): Promise<string> {
    if (!uploadedSessionId.value) {
      const form = new FormData()
      form.append('sceneId', input.sceneId)
      form.append('preparedSessionId', input.preparedSessionId)
      form.append('turns', JSON.stringify(input.turns))
      form.append('engine', input.engine)
      form.append('channelHint', input.channelHint)
      form.append('durationSeconds', String(input.durationSeconds))
      if (input.recording) form.append(input.channelHint === 'VIDEO' ? 'video' : 'audio', input.recording, 'interview.webm')
      const saved = await api.post<ApiEnvelope<{ id: string }>>('/voice/sessions', form, { timeout: 180000 })
      uploadedSessionId.value = saved.data.data.id
      submissionStage.value = 'uploaded'
    }
    await api.post(`/training-sessions/${uploadedSessionId.value}/finish`, null, { timeout: MODEL_REQUEST_TIMEOUT_MS })
    submissionStage.value = 'reportReady'
    return uploadedSessionId.value
  }
  return { uploadedSessionId, submissionStage, submitReport }
}
