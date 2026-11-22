<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { api, errorMessage } from '@/lib/api'
import type { TrainingSession } from '@/lib/types'
const props = defineProps<{ session: TrainingSession | null; rounds: Array<{ roundNo: number; question: string }> }>()
const emit = defineEmits<{ error: [message: string] }>()
const session = computed(() => props.session)
const rounds = computed(() => props.rounds)
// V-06：视频逐题自评（镜头位置 / 信息组织 / 开场收尾）
interface SelfReviewEntry { roundNo: number; camera: boolean; structure: boolean; opening: boolean; note: string }
const selfReview = shallowRef<SelfReviewEntry[]>([])
const reviewSaved = shallowRef(false)
const reviewSaving = shallowRef(false)

function initSelfReview(): void {
  const marks = session.value?.delivery?.marks ?? []
  const saved = new Map((session.value?.delivery?.selfReview ?? []).map((item) => [item.roundNo, item]))
  const source = marks.length ? marks.map((mark, index) => ({ roundNo: index + 1, text: mark.text })) : rounds.value.map((round) => ({ roundNo: round.roundNo, text: round.question }))
  selfReview.value = source.map((item) => {
    const existing = saved.get(item.roundNo)
    return {
      roundNo: item.roundNo,
      camera: existing?.camera ?? false,
      structure: existing?.structure ?? false,
      opening: existing?.opening ?? false,
      note: existing?.note ?? '',
    }
  })
}

async function saveSelfReview(): Promise<void> {
  if (!session.value || reviewSaving.value) return
  reviewSaving.value = true
  try {
    await api.put(`/training-sessions/${session.value.id}/self-review`, { items: selfReview.value })
    reviewSaved.value = true
  } catch (reason) {
    emit('error', errorMessage(reason))
  } finally {
    reviewSaving.value = false
  }
}

watch(session, () => initSelfReview(), { immediate: true })


</script>
<template>
      <section v-if="session?.channel === 'VIDEO' && selfReview.length" class="self-review panel">
        <header><h2>逐题自评</h2><span>回看录像后勾选，指标会随报告保存</span></header>
        <ul>
          <li v-for="item in selfReview" :key="item.roundNo">
            <span class="num">第 {{ item.roundNo }} 题</span>
            <label><input v-model="item.camera" type="checkbox" /> 镜头位置合适</label>
            <label><input v-model="item.structure" type="checkbox" /> 信息有结构</label>
            <label><input v-model="item.opening" type="checkbox" /> 开场与收尾清楚</label>
            <input v-model="item.note" class="field note" maxlength="200" placeholder="补充一句（可选）" />
          </li>
        </ul>
        <button class="button secondary" type="button" :disabled="reviewSaving" @click="saveSelfReview">
          {{ reviewSaving ? '保存中…' : reviewSaved ? '已保存 ✓ 再保存一次' : '保存自评' }}
        </button>
      </section>
</template>
<style scoped>
.self-review header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.self-review h2 { margin: 0; }
.self-review header span { color: var(--text-3); font-size: 11.5px; }
.self-review ul { list-style: none; margin: 14px 0; padding: 0; display: grid; gap: 10px; }
.self-review li { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; }
.self-review li .num { color: var(--text-3); font-size: 11.5px; }
.self-review label { display: inline-flex; align-items: center; gap: 5px; color: var(--text-2); font-size: 12px; }
.self-review .note { margin-left: auto; min-width: 180px; max-width: 260px; }
.self-review h2 { font-size:18px;font-weight:600; }.self-review header span { display:none; }
</style>
