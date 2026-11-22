import { shallowRef } from 'vue'
import { api, errorMessage } from '@/lib/api'
import type { ApiEnvelope, TrainingSession } from '@/lib/types'

export function useReportSharing(getSession: () => TrainingSession | null, onError: (message: string) => void) {
  // 教练查看链接（只读 + 时间点批注 + 可撤销 + 服务端打印版报告）
  const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'
  const shareLink = shallowRef('')
  const shareToken = shallowRef('')
  const shareNote = shallowRef('')
  const shareBusy = shallowRef(false)
  const revokingShare = shallowRef(false)

  async function issueShareLink(): Promise<{ url: string; token: string }> {
    const response = await api.post<ApiEnvelope<{ url: string; expiresAt: number }>>(`/share/training-sessions/${getSession()!.id}`)
    const url = response.data.data.url
    return { url, token: url.split('/').filter(Boolean).pop() ?? '' }
  }

  async function createShareLink(): Promise<void> {
    if (!getSession() || shareBusy.value) return
    shareBusy.value = true
    try {
      const issued = await issueShareLink()
      shareToken.value = issued.token
      shareLink.value = `${location.origin}${issued.url}`
      shareNote.value = ''
      await navigator.clipboard?.writeText(shareLink.value).catch(() => undefined)
    } catch (reason) {
      onError(errorMessage(reason))
    } finally {
      shareBusy.value = false
    }
  }

  async function openShareReport(): Promise<void> {
    if (!getSession() || shareBusy.value) return
    shareBusy.value = true
    try {
      if (!shareToken.value) shareToken.value = (await issueShareLink()).token
      if (!shareToken.value) return
      window.open(`${API_BASE}/share/${shareToken.value}/report`, '_blank', 'noopener')
    } catch (reason) {
      onError(errorMessage(reason))
    } finally {
      shareBusy.value = false
    }
  }

  async function revokeShare(): Promise<void> {
    if (!shareToken.value || revokingShare.value) return
    revokingShare.value = true
    try {
      await api.delete(`/share/${shareToken.value}`)
      shareToken.value = ''
      shareLink.value = ''
      shareNote.value = '已撤销：这个链接现在打不开了，需要时可以重新生成一个。'
    } catch (reason) {
      onError(errorMessage(reason))
    } finally {
      revokingShare.value = false
    }
  }

  return { shareLink, shareToken, shareNote, shareBusy, revokingShare, createShareLink, openShareReport, revokeShare }
}
