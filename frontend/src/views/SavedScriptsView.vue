<script setup lang="ts">
import { computed, onMounted, shallowRef, watch } from 'vue'
import { ArrowLeft } from 'lucide-vue-next'

import ScriptVersionCard from '@/components/scenes/ScriptVersionCard.vue'
import { useScriptPreview } from '@/composables/useScriptPreview'
import { api, errorMessage } from '@/lib/api'
import type { ApiEnvelope, Scene, ScriptVersion } from '@/lib/types'

const versions = shallowRef<ScriptVersion[]>([])
const scenes = shallowRef<Scene[]>([])
const loading = shallowRef(true)
const error = shallowRef('')
const { previewingId, playingId, playPreview } = useScriptPreview((message) => { error.value = message })
const favoritingIds = shallowRef<string[]>([])
const deletingIds = shallowRef<string[]>([])
const page = shallowRef(1)
const PAGE_SIZE = 9
const onlyFavorites = shallowRef(false)
const filtered = computed(() => versions.value.filter((item) => !onlyFavorites.value || item.favorite))

const sceneTitles = computed(() => new Map(scenes.value.map((scene) => [scene.id, scene.title])))
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const paged = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))

watch([onlyFavorites, pageCount], () => { page.value = Math.max(1, Math.min(page.value, pageCount.value)) })
onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [scriptResponse, sceneResponse] = await Promise.all([
      api.get<ApiEnvelope<ScriptVersion[]>>('/scripts'),
      api.get<ApiEnvelope<Scene[]>>('/scenes', { params: { size: 100 } }).catch(() => null),
    ])
    versions.value = scriptResponse.data.data
    scenes.value = sceneResponse ? sceneResponse.data.data : []
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    loading.value = false
  }
}

async function favorite(version: ScriptVersion): Promise<void> {
  if (favoritingIds.value.includes(version.id)) return
  favoritingIds.value = [...favoritingIds.value, version.id]
  error.value = ''
  try {
    const response = await api.post<ApiEnvelope<{ favorite: boolean }>>(`/scripts/${version.id}/favorite`)
    versions.value = versions.value.map((item) => item.id === version.id ? { ...item, favorite: response.data.data.favorite } : item)
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    favoritingIds.value = favoritingIds.value.filter((id) => id !== version.id)
  }
}

async function remove(version: ScriptVersion): Promise<void> {
  if (deletingIds.value.includes(version.id)) return
  if (!window.confirm('确定删除这个版本吗？删除后无法恢复。')) return
  deletingIds.value = [...deletingIds.value, version.id]
  error.value = ''
  try {
    await api.delete(`/scripts/${version.id}`)
    versions.value = versions.value.filter((item) => item.id !== version.id)
    if (page.value > pageCount.value) page.value = pageCount.value
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    deletingIds.value = deletingIds.value.filter((id) => id !== version.id)
  }
}
</script>

<template>
  <div class="page saved-page">
    <RouterLink class="back" to="/scripts"><ArrowLeft :size="13" :stroke-width="1.8" aria-hidden="true" /> 返回话术优化</RouterLink>

    <header class="page-heading">
      <div>
        <p class="eyebrow">话术版本</p>
        <h1 class="page-title">我的话术库</h1>
        <p class="page-lead">生成记录和收藏统一保存在这里。</p>
      </div>
      <span class="count num">{{ versions.length }} 个</span>
    </header>

    <div class="actions"><button class="button secondary" @click="onlyFavorites = false; page = 1">全部话术</button><button class="button secondary" @click="onlyFavorites = true; page = 1">已收藏</button><RouterLink class="button secondary" to="/favorites">收藏的场景</RouterLink></div>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <div v-if="loading" class="skeleton loading" />

    <div v-else-if="!versions.length" class="empty">
      <p>还没有保存过版本。</p>
      <RouterLink to="/scripts">去话术优化生成三种风格 →</RouterLink>
    </div>

    <template v-else>
      <div class="versions">
        <ScriptVersionCard
          v-for="version in paged"
          :key="version.id"
          :version="version"
          :preview-loading="previewingId === version.id"
          :preview-disabled="!!previewingId && previewingId !== version.id"
          :preview-playing="playingId === version.id"
          :favorite-loading="favoritingIds.includes(version.id)"
          :deleting="deletingIds.includes(version.id)"
          :scene-title="sceneTitles.get(version.sceneId ?? '') ?? '历史场景'"
          show-actions
          allow-delete
          @favorite="favorite"
          @preview="playPreview"
          @remove="remove"
        />
      </div>

      <nav v-if="pageCount > 1" class="pager" aria-label="版本分页">
        <button class="text-btn" type="button" :disabled="page <= 1" @click="page -= 1">上一页</button>
        <span class="num">{{ page }} / {{ pageCount }}</span>
        <button class="text-btn" type="button" :disabled="page >= pageCount" @click="page += 1">下一页</button>
      </nav>
    </template>
  </div>
</template>

<style scoped>
.saved-page { max-width: 1040px; }
.back { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 18px; color: var(--text-3); font-size: 12px; }
.back:hover { color: var(--text-2); }
.count { color: var(--text-3); font-size: 12px; }
.loading { min-height: 220px; }
.versions { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.pager { display: flex; align-items: center; justify-content: center; gap: 18px; padding-top: 22px; color: var(--text-3); font-size: 12px; }
.text-btn { padding: 0; border: 0; background: none; color: var(--text-3); font-size: 12px; cursor: pointer; }
.text-btn:disabled { opacity: .45; cursor: not-allowed; }
.text-btn:hover:not(:disabled) { color: var(--text); }
</style>
<style scoped>
.saved-page { max-width: 860px; }
.page-title { font-size: clamp(28px, 3vw, 36px); letter-spacing: -.02em; }
.page-lead { margin-top: 10px; font-size: 14px; }
.page-heading > .count { color: var(--text-3); font-size: 13px; }
.empty { margin-top: 18px; padding: 28px 0; border-top: 1px solid var(--divider); display: grid; gap: 10px; justify-items: start; }
.empty p { margin: 0; color: var(--text-3); font-size: 14px; }
.empty a { color: var(--text-2); font-size: 13.5px; }
.pager { margin-top: 24px; }
</style>
