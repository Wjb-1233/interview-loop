import { onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'

import { api, errorMessage } from '@/lib/api'
import type { DashboardData, DashboardFilters } from '@/lib/dashboard'
import type { ApiEnvelope } from '@/lib/types'

export function useDashboard() {
  const data = shallowRef<DashboardData | null>(null)
  const loading = shallowRef(false)
  const error = shallowRef('')
  const filters = shallowRef<DashboardFilters>({ channel: '', sceneId: '', anchorSessionId: '' })
  let controller: AbortController | null = null

  async function load() {
    controller?.abort()
    const request = new AbortController()
    controller = request
    loading.value = true
    error.value = ''
    try {
      const value = filters.value
      const response = await api.get<ApiEnvelope<DashboardData>>('/dashboard', { signal: request.signal, params: { channel: value.channel || undefined, scene_id: value.sceneId || undefined, anchor_session_id: value.anchorSessionId || undefined } })
      if (!request.signal.aborted) data.value = response.data.data
    } catch (reason) {
      if (!request.signal.aborted) error.value = errorMessage(reason)
    } finally {
      if (controller === request) loading.value = false
    }
  }

  function updateFilters(patch: Partial<DashboardFilters>) {
    filters.value = { ...filters.value, ...(('channel' in patch || 'sceneId' in patch) ? { anchorSessionId: '' } : {}), ...patch }
  }
  function resetFilters() { filters.value = { channel: '', sceneId: '', anchorSessionId: '' } }
  watch(filters, load)
  onMounted(load)
  onBeforeUnmount(() => controller?.abort())
  return { data, loading, error, filters, load, updateFilters, resetFilters }
}
