import { shallowRef } from 'vue'
import { api, errorMessage } from '@/lib/api'
import type { ApiEnvelope, Evaluation, TrainingMessage, TrainingSession } from '@/lib/types'

export function useTrainingReport(sessionId: () => string) {
  const evaluation = shallowRef<Evaluation | null>(null)
  const messages = shallowRef<TrainingMessage[]>([])
  const session = shallowRef<TrainingSession | null>(null)
  const error = shallowRef('')
  const rescoring = shallowRef(false)

  async function loadReport(): Promise<void> {
    const response = await api.get<ApiEnvelope<Evaluation>>(`/evaluations/${sessionId()}`)
    const sessionResponse = await api.get<ApiEnvelope<TrainingSession>>(`/training-sessions/${sessionId()}`).catch(() => null)
    if (sessionResponse) {
      session.value = sessionResponse.data.data
      messages.value = sessionResponse.data.data.messages
    }
    evaluation.value = response.data.data
  }

  async function rescore(): Promise<void> {
    if (rescoring.value) return
    rescoring.value = true
    error.value = ''
    try {
      await api.post(`/evaluations/${sessionId()}?force=true`)
      await loadReport()
    } catch (reason) { error.value = errorMessage(reason) }
    finally { rescoring.value = false }
  }
  return { evaluation, messages, session, error, rescoring, loadReport, rescore }
}
