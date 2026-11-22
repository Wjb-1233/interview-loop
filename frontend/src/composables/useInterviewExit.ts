import { inject, onBeforeUnmount, onMounted, readonly, shallowRef } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { api, authorizedFetch, errorMessage } from '@/lib/api'
import { activeTrainingAttemptKey } from '@/lib/activeTrainingAttempt'

/** A training attempt is temporary until the learner explicitly ends it. */
export function useInterviewExit(sessionId: () => string, retained: () => boolean, onError: (message: string) => void) {
  const controller = inject(activeTrainingAttemptKey)
  if (!controller) throw new Error('Training attempt controller must be provided by App')
  const leaving = shallowRef(false)
  let discarded = false
  let request: Promise<void> | null = null

  function clearDrafts(id: string): void {
    try {
      const prefix = `yanjie:draft:${id}:`
      for (let index = localStorage.length - 1; index >= 0; index--) {
        const key = localStorage.key(index)
        if (key?.startsWith(prefix)) localStorage.removeItem(key)
      }
    } catch { /* Storage can be unavailable in private browsing. */ }
  }

  async function discard(): Promise<void> {
    const id = sessionId()
    if (!id || retained() || discarded) return
    request ??= api.post(`/training-sessions/${id}/discard`).then(() => { discarded = true; clearDrafts(id) }).finally(() => { request = null })
    await request
  }

  function discardOnUnload(): void {
    const id = sessionId()
    if (!id || retained() || discarded) return
    clearDrafts(id)
    void authorizedFetch(`/training-sessions/${id}/discard`, { method: 'POST', keepalive: true }).catch(() => {})
  }

  async function cleanupBeforeLogout(): Promise<void> {
    try { await discard() }
    catch (reason) { onError(`退出清理未完成：${errorMessage(reason)}，请重试退出。`); throw reason }
  }

  onBeforeRouteLeave(async () => {
    leaving.value = true
    try {
      await discard()
      return true
    } catch (reason) {
      onError(`退出清理未完成：${errorMessage(reason)}，请重试退出。`)
      return false
    } finally {
      leaving.value = false
    }
  })
  const unregister = controller.register({ sessionId, retained, discard: cleanupBeforeLogout })
  onMounted(() => {
    window.addEventListener('pagehide', discardOnUnload)
  })
  onBeforeUnmount(() => {
    unregister()
    window.removeEventListener('pagehide', discardOnUnload)
    discardOnUnload()
  })
  return { leaving: readonly(leaving) }
}
