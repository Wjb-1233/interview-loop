<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import MiniBarChart from '@/components/admin/MiniBarChart.vue'
import type { AdminLearnerRow } from '@/lib/types'

const props = defineProps<{ learners: AdminLearnerRow[]; loading: boolean }>()
const emit = defineEmits<{ export: []; report: [userId: string] }>()
const router = useRouter()

// 测试账号判定规则（与下方小字说明保持一致）
const TEST_EMAIL_PREFIXES = ['self-review-', 'a11y-rp-']
const TEST_NAMES = ['自评测试', '报告无障碍']
const PAGE_SIZE = 20

const keyword = ref('')
const hideTest = ref(true)
const page = ref(1)

const isTestAccount = (item: AdminLearnerRow) => {
  const email = item.email.toLowerCase()
  return TEST_EMAIL_PREFIXES.some((prefix) => email.startsWith(prefix)) || TEST_NAMES.some((name) => item.name.includes(name))
}

const registered = computed(() => props.learners.filter((item) => !isTestAccount(item)).length)
const scoped = computed(() => (hideTest.value ? props.learners.filter((item) => !isTestAccount(item)) : props.learners))
const filtered = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  if (!query) return scoped.value
  return scoped.value.filter((item) => item.name.toLowerCase().includes(query) || item.email.toLowerCase().includes(query))
})

const stats = computed(() => {
  const rows = scoped.value
  return {
    total: rows.length,
    trained: rows.filter((item) => item.sessions > 0).length,
    sessions: rows.reduce((sum, item) => sum + item.sessions, 0),
    hidden: props.learners.length - registered.value,
  }
})
const topLearners = computed(() => {
  // MiniBarChart 用 label 作为 key，同名学员（如批量生成的测试账号）必须补序号
  const seen = new Map<string, number>()
  return [...scoped.value]
    .filter((item) => item.sessions > 0)
    .sort((left, right) => right.sessions - left.sessions)
    .slice(0, 10)
    .map((item) => {
      const count = (seen.get(item.name) ?? 0) + 1
      seen.set(item.name, count)
      return { label: count > 1 ? `${item.name} #${count}` : item.name, value: item.sessions }
    })
})
const scoreBuckets = computed(() => {
  const buckets = [
    { label: '低于 40 分', value: 0 },
    { label: '40–59 分', value: 0 },
    { label: '60–74 分', value: 0 },
    { label: '75–89 分', value: 0 },
    { label: '90 分以上', value: 0 },
  ]
  for (const item of scoped.value) {
    const score = item.averageScore
    if (score == null) continue
    const index = score < 40 ? 0 : score < 60 ? 1 : score < 75 ? 2 : score < 90 ? 3 : 4
    buckets[index].value += 1
  }
  return buckets
})
const scoredCount = computed(() => scoped.value.filter((item) => item.averageScore != null).length)

const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const paged = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))
watch([keyword, hideTest, () => props.learners], () => { page.value = 1 })
watch(pageCount, (total) => { if (page.value > total) page.value = total })

function go(target: number) {
  page.value = Math.min(pageCount.value, Math.max(1, target))
}

function openDetail(item: AdminLearnerRow) {
  try {
    if (!router.hasRoute('admin-learner')) throw new Error('路由 admin-learner 尚未注册')
    void router.push({ name: 'admin-learner', params: { id: item.userId } })
  } catch (reason) {
    console.warn('[admin-sessions] 学员详情页不可用，回退到报告弹窗', reason)
    emit('report', item.userId)
  }
}

const trainedLabel = (value: string | null) => (value ? new Date(value).toLocaleString('zh-CN') : '还没训练')
</script>

<template>
  <section class="panel table-panel">
    <header>
      <div>
        <p class="eyebrow">训练与报告</p>
        <h2>学员训练概览</h2>
        <p class="panel-hint">点任意一行进入该学员的详情页；需要快速看四维评分时用「查看报告」。</p>
      </div>
      <button class="button" @click="emit('export')">导出全部训练报告</button>
    </header>
    <div v-if="loading" class="loading">正在读取学员数据…</div>
    <template v-else>
      <section class="stats">
        <div class="stat-cards">
          <div class="stat-card"><strong class="num">{{ stats.total }}</strong><span>学员总数</span></div>
          <div class="stat-card"><strong class="num">{{ stats.trained }}</strong><span>有训练记录的学员</span></div>
          <div class="stat-card"><strong class="num">{{ stats.sessions }}</strong><span>总训练场次</span></div>
        </div>
        <div class="stat-charts">
          <section class="chart">
            <header class="chart-head"><h3>训练场次 Top 10 学员</h3><span>按场次排序</span></header>
            <MiniBarChart v-if="topLearners.length" :items="topLearners" orientation="horizontal" unit="次" />
            <p v-else class="chart-empty">还没有学员开始训练。</p>
          </section>
          <section class="chart">
            <header class="chart-head"><h3>平均分分布</h3><span>{{ scoredCount }} 位学员有平均分</span></header>
            <MiniBarChart :items="scoreBuckets" orientation="horizontal" unit="人" />
          </section>
        </div>
      </section>
      <div class="toolbar">
        <input v-model="keyword" type="search" class="search" aria-label="搜索学员" placeholder="搜索姓名或邮箱" />
        <label class="toggle">
          <input v-model="hideTest" type="checkbox" />
          <span>隐藏测试账号（{{ stats.hidden }}）</span>
        </label>
        <span class="toolbar-hint">匹配规则：邮箱以 self-review- 或 a11y-rp- 开头，或姓名为「自评测试」「报告无障碍」</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>学员</th><th>邮箱</th><th>训练场次</th><th>平均分</th><th>最近训练</th><th>操作</th></tr></thead>
          <tbody>
            <tr
              v-for="item in paged"
              :key="item.userId"
              class="row"
              role="button"
              tabindex="0"
              :aria-label="`查看 ${item.name} 的学员详情`"
              @click="openDetail(item)"
              @keydown.enter.prevent="openDetail(item)"
              @keydown.space.prevent="openDetail(item)"
            >
              <td class="name">{{ item.name }}</td>
              <td class="email">{{ item.email }}</td>
              <td class="num">{{ item.sessions }}</td>
              <td class="num">{{ item.averageScore ?? '—' }}</td>
              <td class="muted">{{ trainedLabel(item.lastTrainedAt) }}</td>
              <td><button class="text-button" type="button" @click.stop="emit('report', item.userId)">查看报告</button></td>
            </tr>
          </tbody>
        </table>
        <p v-if="!paged.length" class="empty">{{ keyword.trim() ? '没有匹配的学员。' : '目前还没有学员。' }}</p>
      </div>
      <footer class="pager">
        <span class="pager-info">第 {{ page }} / {{ pageCount }} 页 · 共 {{ filtered.length }} 位学员</span>
        <div class="pager-actions">
          <button class="button secondary compact" type="button" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
          <button class="button secondary compact" type="button" :disabled="page >= pageCount" @click="go(page + 1)">下一页</button>
        </div>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.table-panel { overflow: hidden; }
header { padding: 24px 24px 18px; display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
h2 { margin: 0; font: 600 22px var(--font-ui); line-height: 1.3; }
.panel-hint { margin: 8px 0 0; color: var(--text-3); font-size: 12px; }
.stats { display: grid; gap: 12px; padding: 0 24px 16px; }
.stat-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.stat-card { min-height: 84px; padding: 14px 16px; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid var(--divider); border-radius: 12px; background: var(--overlay-1); }
.stat-card strong { font-size: 26px; line-height: 1; font-weight: 650; color: var(--text); }
.stat-card span { color: var(--text-3); font-size: 12px; }
.stat-charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.chart { display: grid; gap: 12px; align-content: start; padding: 16px; border: 1px solid var(--divider); border-radius: 12px; background: var(--overlay-1); }
.chart-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.chart-head h3 { margin: 0; color: var(--text); font-size: 13px; font-weight: 650; }
.chart-head span { color: var(--text-3); font-size: 11.5px; }
.chart-empty { margin: 0; padding: 10px 0; color: var(--text-3); font-size: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 0 24px 14px; }
.search { width: 240px; min-height: 34px; padding: 6px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--card); color: var(--text); font-size: 12.5px; }
.search:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.toggle { display: inline-flex; align-items: center; gap: 8px; color: var(--text-2); font-size: 12.5px; cursor: pointer; }
.toggle input { width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; }
.toolbar-hint { flex: 1 1 260px; color: var(--text-3); font-size: 11.5px; }
.table-wrap { overflow: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 11px 14px; border-top: 1px solid var(--line); text-align: left; font-size: 12px; white-space: nowrap; }
th { color: var(--ink-soft); background: var(--overlay-1); }
.name { color: var(--text); font-weight: 600; }
.email { color: var(--text-2); }
.muted { color: var(--text-3); }
.text-button { border: 0; background: none; color: var(--text-2); cursor: pointer; font-weight: 700; font-size: 12px; }
.text-button:hover { color: var(--text); }
.loading, .empty { padding: 26px; color: var(--ink-soft); }
tbody tr.row { cursor: pointer; transition: background .14s var(--ease); }
tbody tr.row:hover { background: var(--overlay-2); }
tbody tr.row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.pager { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 24px 16px; border-top: 1px solid var(--divider); }
.pager-info { color: var(--text-3); font-size: 12px; }
.pager-actions { display: flex; gap: 8px; }
.compact { min-height: 30px; padding: 4px 12px; font-size: 12px; }
@media (max-width: 900px) {
  .stat-cards, .stat-charts { grid-template-columns: minmax(0, 1fr); }
}
</style>
