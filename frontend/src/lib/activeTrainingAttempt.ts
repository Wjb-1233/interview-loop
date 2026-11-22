import type { InjectionKey } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { api } from '@/lib/api'

export function trainingAttemptId(route: Pick<RouteLocationNormalizedLoaded, 'name' | 'params' | 'query'>): string {
  if (route.name === 'training') return String(route.params.id ?? '')
  return ['voice', 'video'].includes(String(route.name)) ? String(route.query.sessionId ?? '') : ''
}

/** One controller per application. Authentication has no training dependencies. */
export function createActiveTrainingAttempt() {
  let current: { sessionId: () => string; retained: () => boolean; discard: () => Promise<void> } | null = null
  return {
    register(attempt: NonNullable<typeof current>) {
      current = attempt
      return () => { if (current === attempt) current = null }
    },
    async discardBeforeLogout(fallbackId: string) {
      if (current) await current.discard()
      else if (fallbackId) await api.post(`/training-sessions/${fallbackId}/discard`)
    },
  }
}

export const activeTrainingAttemptKey: InjectionKey<ReturnType<typeof createActiveTrainingAttempt>> = Symbol('active-training-attempt')
