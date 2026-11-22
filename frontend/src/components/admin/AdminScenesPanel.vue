<script setup lang="ts">
import QuestionRubricEditor from './QuestionRubricEditor.vue'
import { importedRubric } from '@/lib/questionRubric'
import { computed, reactive, shallowRef, watch } from 'vue'
import SelectField from '@/components/ui/SelectField.vue'
import type { AdminSceneRecord, QuestionItem } from '@/lib/types'
import { DIFFICULTY_LEVELS, normalizeSceneCategory, SCENE_CATEGORIES } from '@/lib/sceneTaxonomy'

const props = defineProps<{ scenes: AdminSceneRecord[]; busy: boolean }>()
const emit = defineEmits<{ save: [value: Omit<AdminSceneRecord, 'id'>, id: string | null]; deactivate: [id: string] }>()
const empty = (): Omit<AdminSceneRecord, 'id'> => ({ category: 'HR 初面', title: '', industry: '', position: '', roleName: '', difficulty: '中级', background: '', goal: '', coreIdea: '', tags: [], openingLine: '', questionBank: [], active: true })
const selectedId = shallowRef<string | null>(null)
const form = reactive(empty())
const tagText = shallowRef('')
const keyword = shallowRef('')
const statusFilter = shallowRef<'all' | 'open' | 'closed'>('all')
const sortBy = shallowRef<'recent' | 'trained' | 'title'>('recent')
const bankError = shallowRef('')
const MAX_QUESTIONS = 20
const dimensions = ['', '内容与逻辑', '贴合问题', '信息完整', '表达干净']
const editing = computed(() => selectedId.value !== null)
const interviewScenes = computed(() => props.scenes.filter((item) => item.category !== '基础能力提升'))
const filteredScenes = computed(() => {
  const word = keyword.value.trim()
  const rows = interviewScenes.value.filter((item) => {
    if (word && !`${item.title}${item.position}${item.industry}${item.category}${item.roleName}`.includes(word)) return false
    if (statusFilter.value === 'open') return item.active
    if (statusFilter.value === 'closed') return !item.active
    return true
  })
  if (sortBy.value === 'trained') {
    return [...rows].sort((a, b) => (b.sessionCount ?? 0) - (a.sessionCount ?? 0))
  }
  if (sortBy.value === 'title') {
    return [...rows].sort((a, b) => a.title.localeCompare(b.title, 'zh-CN'))
  }
  // 默认把开放中的排前面，停用的沉底，避免测试场景占满首屏
  return [...rows].sort((a, b) => Number(b.active) - Number(a.active))
})

const openCount = computed(() => interviewScenes.value.filter((item) => item.active).length)

// 一页 6 张卡（两列三行），让右侧列表与左侧表单高度接近
const PAGE_SIZE = 6
const page = shallowRef(1)
const pageCount = computed(() => Math.max(1, Math.ceil(filteredScenes.value.length / PAGE_SIZE)))
const pagedScenes = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return filteredScenes.value.slice(start, start + PAGE_SIZE)
})

watch([keyword, statusFilter, sortBy], () => { page.value = 1 })
watch(pageCount, (total) => { if (page.value > total) page.value = total })

function goPage(next: number): void {
  page.value = Math.min(pageCount.value, Math.max(1, next))
}

function edit(item?: AdminSceneRecord) {
  selectedId.value = item?.id ?? null
  Object.assign(form, item
    ? { ...item, category: normalizeSceneCategory(item.category) === '全部' ? 'HR 初面' : normalizeSceneCategory(item.category), questionBank: (item.questionBank ?? []).map((q) => ({ ...q })) }
    : empty())
  tagText.value = item?.tags.join('，') ?? ''
  bankError.value = ''
}

function cleanBank(questions: QuestionItem[]): QuestionItem[] {
  const bank = questions.filter((item) => item.text.trim()).map((item) => ({
    text: item.text.trim(), dimension: item.dimension?.trim() || null, difficulty: item.difficulty?.trim() || null,
    ...(item.rubric ? { rubric: item.rubric } : {}),
  }))
  if (bank.length > MAX_QUESTIONS) throw new Error(`每个场景最多 ${MAX_QUESTIONS} 道题，请减少后再保存。`)
  if (bank.some((item) => item.text.length < 2 || item.text.length > 300)) throw new Error('每道题的正文需要 2–300 字。')
  if (bank.some((item) => (item.dimension?.length ?? 0) > 20 || (item.difficulty?.length ?? 0) > 20)) throw new Error('考察维度和题目难度不能超过 20 字。')
  return bank
}

function exportBank(): void {
  const payload = JSON.stringify(form.questionBank, null, 2)
  const blob = new Blob([payload], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${form.title || '场景'}-题库.json`
  link.click()
  URL.revokeObjectURL(url)
}

async function importBank(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const raw = JSON.parse(await file.text())
    const list = Array.isArray(raw) ? raw : Array.isArray(raw?.questionBank) ? raw.questionBank : null
    if (!list) throw new Error('需要 JSON 数组，或包含 questionBank 数组的对象。')
    const bank = list.map((item: unknown): QuestionItem => {
      if (typeof item === 'string') return { text: item, dimension: null, difficulty: null }
      if (!item || typeof item !== 'object' || !('text' in item) || typeof item.text !== 'string') throw new Error('每道题需要 text 正文，可选 dimension 维度和 difficulty 难度。')
      return {
        text: item.text,
        dimension: 'dimension' in item && typeof item.dimension === 'string' ? item.dimension : null,
        difficulty: 'difficulty' in item && typeof item.difficulty === 'string' ? item.difficulty : null,
        ...('rubric' in item ? { rubric: importedRubric(item.rubric) } : {}),
      }
    })
    form.questionBank = cleanBank(bank)
    bankError.value = ''
  } catch (reason) {
    bankError.value = `导入失败：${reason instanceof SyntaxError ? '文件不是有效的 JSON。' : reason instanceof Error ? reason.message : '请检查题目格式。'}`
  }
}

function addQuestion() {
  if (form.questionBank.length >= MAX_QUESTIONS) return
  form.questionBank.push({ text: '', dimension: '', difficulty: '' })
}

function removeQuestion(index: number) {
  form.questionBank.splice(index, 1)
}

function submit() {
  let bank: QuestionItem[]
  try { bank = cleanBank(form.questionBank); bankError.value = '' }
  catch (reason) { bankError.value = (reason as Error).message; return }
  emit('save', {
    ...form,
    tags: tagText.value.split(/[，,]/).map((tag) => tag.trim()).filter(Boolean),
    questionBank: bank,
  }, selectedId.value)
  if (!selectedId.value) edit()
}
</script>

<template>
  <section class="catalog-grid">
    <form class="panel editor" @submit.prevent="submit">
      <p class="eyebrow">场景设计</p><h2>{{ editing ? '编辑训练场景' : '设计新场景' }}</h2><p class="editor-help">按招聘阶段设计面试问题，再指定行业、岗位和难度。基础能力练习在学员的能力提升页展示。</p>
      <label>场景名称<input v-model.trim="form.title" class="field" required minlength="2" maxlength="100"></label>
      <div class="two"><label>场景分类<SelectField :model-value="form.category" :options="SCENE_CATEGORIES.slice(1).map((item) => ({ value: item, label: item }))" aria-label="场景分类" @update:model-value="form.category = $event" /></label><label>难度<SelectField :model-value="form.difficulty" :options="DIFFICULTY_LEVELS.map((level) => ({ value: level.name, label: level.name, hint: level.cue }))" aria-label="难度" @update:model-value="form.difficulty = $event" /></label></div>
      <div class="two"><label>行业<input v-model.trim="form.industry" class="field" required></label><label>岗位<input v-model.trim="form.position" class="field" required></label></div>
      <label>面试官角色<input v-model.trim="form.roleName" class="field" required></label>
      <label>场景背景<textarea v-model.trim="form.background" class="field" rows="3" required minlength="10" /></label>
      <label>训练目标<textarea v-model.trim="form.goal" class="field" rows="2" required /></label>
      <label>场景核心思想（大模型每轮追问都围绕它）<textarea v-model.trim="form.coreIdea" class="field" rows="2" maxlength="500" placeholder="例如：考察候选人能否用可核对的事实说明自己的贡献，而不是空泛表态。" /></label>
      <label>开场问题（选填）<input v-model.trim="form.openingLine" class="field" placeholder="留空则由大模型根据场景背景与学员简历生成"></label>

      <div class="bank">
        <div class="bank-head">
          <div>
            <strong>场景题目 · {{ form.questionBank.length }} / {{ MAX_QUESTIONS }}</strong>
            <span>按训练轮数依次选用，结合核心思想、JD 与简历继续追问。每个场景最多 {{ MAX_QUESTIONS }} 道题。</span>
          </div>
          <div class="bank-tools">
            <button class="button secondary compact" type="button" :disabled="form.questionBank.length >= MAX_QUESTIONS" @click="addQuestion">+ 添加一题</button>
            <button
              class="button secondary compact"
              type="button"
              :disabled="!form.questionBank.length"
              :title="form.questionBank.length ? '导出当前题目为 JSON' : '还没有题目'"
              @click="exportBank"
            >导出</button>
            <label class="button secondary compact import-label">
              导入
              <input type="file" accept="application/json,.json" aria-label="导入场景题目" hidden @change="importBank">
            </label>
          </div>
        </div>
        <p v-if="bankError" class="error-banner" role="alert">{{ bankError }}</p>
        <p v-if="!form.questionBank.length" class="bank-empty">还没有预设题目。不设置时，面试官按场景核心思想与简历出题。</p>
        <div v-for="(item, index) in form.questionBank" :key="index" class="bank-row">
          <span class="bank-index num">{{ String(index + 1).padStart(2, '0') }}</span>
          <textarea v-model="item.text" class="field" rows="2" minlength="2" maxlength="300" :aria-label="`第 ${index + 1} 题正文`" placeholder="例如：先做一个简短的自我介绍" />
          <button class="bank-remove" type="button" aria-label="删除这一题" @click="removeQuestion(index)">✕</button>
          <div class="bank-meta">
            <label>考察维度<SelectField :model-value="item.dimension || '__none'" :options="dimensions.map((dimension) => ({ value: dimension || '__none', label: dimension || '不指定' }))" :aria-label="`第 ${index + 1} 题考察维度`" compact @update:model-value="item.dimension = $event === '__none' ? null : $event" /></label>
            <label>题目难度<SelectField :model-value="item.difficulty || '__none'" :options="[{ value: '__none', label: '难度不限' }, ...DIFFICULTY_LEVELS.map((level) => ({ value: level.name, label: level.name }))]" :aria-label="`第 ${index + 1} 题难度`" compact @update:model-value="item.difficulty = $event === '__none' ? null : $event" /></label>
          </div>
          <QuestionRubricEditor v-model="item.rubric" :index="index" />
        </div>
      </div>

      <label>标签（逗号分隔）<input v-model="tagText" class="field"></label>
      <label class="check"><input v-model="form.active" type="checkbox"> 对学员开放</label>
      <div class="actions"><button class="button" :disabled="busy">{{ editing ? '保存修改' : '创建场景' }}</button><button v-if="editing" class="button secondary" type="button" @click="edit()">取消编辑</button></div>
    </form>
    <section class="panel listing">
      <header class="listing-head">
        <div>
          <p class="eyebrow">场景</p>
          <h2>场景库</h2>
        </div>
        <p class="listing-count"><strong>{{ openCount }}</strong> 个开放<em>/</em>{{ interviewScenes.length }} 个场景</p>
      </header>

      <div class="toolbar">
        <input v-model="keyword" class="field search" type="search" placeholder="搜索场景或岗位" aria-label="搜索场景" />
        <div class="seg" role="group" aria-label="按状态筛选">
          <button type="button" :class="{ active: statusFilter === 'all' }" @click="statusFilter = 'all'">全部</button>
          <button type="button" :class="{ active: statusFilter === 'open' }" @click="statusFilter = 'open'">开放</button>
          <button type="button" :class="{ active: statusFilter === 'closed' }" @click="statusFilter = 'closed'">停用</button>
        </div>
        <select v-model="sortBy" class="field sort" aria-label="排序方式">
          <option value="recent">最近新增</option>
          <option value="trained">按训练次数</option>
          <option value="title">按名称</option>
        </select>
      </div>

      <p v-if="!filteredScenes.length" class="empty-line">没有匹配的场景。</p>

      <div class="scene-grid">
        <article v-for="item in pagedScenes" :key="item.id" class="scene-card" :class="{ off: !item.active }">
          <div class="card-top">
            <span class="pill">{{ item.category }}</span>
            <span class="state" :class="{ off: !item.active }"><i />{{ item.active ? '开放' : '停用' }}</span>
          </div>
          <h3 :title="item.title">{{ item.title }}</h3>
          <p class="meta">{{ item.industry }} · {{ item.position }} · {{ item.difficulty }}</p>
          <dl class="stats">
            <div><dt>题目</dt><dd>{{ item.questionBank?.length ?? 0 }}</dd></div>
            <div><dt>被训练</dt><dd>{{ item.sessionCount ?? 0 }}</dd></div>
            <div><dt>有覆盖</dt><dd>{{ item.coveredSessionCount ?? 0 }}</dd></div>
          </dl>
          <div class="card-actions">
            <button type="button" class="ghost" @click="edit(item)">编辑</button>
            <button v-if="item.active" type="button" class="ghost danger" :disabled="busy" @click="emit('deactivate', item.id)">停用</button>
          </div>
        </article>
      </div>

      <nav v-if="filteredScenes.length" class="pager" aria-label="场景翻页">
        <span class="pager-info">共 {{ filteredScenes.length }} 个 · 第 {{ page }} / {{ pageCount }} 页</span>
        <div class="pager-actions">
          <button type="button" class="pager-btn" :disabled="page === 1" @click="goPage(page - 1)">上一页</button>
          <span class="pager-pos num">{{ page }} / {{ pageCount }}</span>
          <button type="button" class="pager-btn" :disabled="page === pageCount" @click="goPage(page + 1)">下一页</button>
        </div>
      </nav>
    </section>
  </section>
</template>

<style scoped>
.catalog-grid { display:grid; grid-template-columns:minmax(320px,.9fr) minmax(360px,1.1fr); gap:16px; align-items:start; } .editor,.listing { padding:22px; } h2 { margin:0 0 14px;font-size:22px;line-height:1.3; }.editor-help{margin:0 0 18px;color:var(--text-2);font-size:13px;line-height:1.7} label { display:grid; gap:6px; margin:11px 0; color:var(--text-2); font-size:12px; } textarea { resize:vertical; } .two { display:grid; grid-template-columns:1fr 1fr; gap:10px; } .check { display:flex; align-items:center; } .actions { display:flex; gap:8px; flex-wrap:wrap; } .row { padding:13px 0; border-top:1px solid var(--border); display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px 12px; align-items:center; } .row strong,.row small { display:block; } .row small { margin-top:4px; color:var(--text-2); } .row .actions { grid-column:1/-1; } .compact { min-height:32px; padding:5px 9px; font-size:12px; } header { display:flex; justify-content:space-between; align-items:center; } header > span { color:var(--text-2); font-size:12px; } .inactive { background:#f2eeee; color:#899; }
.inactive { border-color:rgba(248,113,113,.25);background:rgba(248,113,113,.09);color:#cf9a92; }
.row:hover { background:var(--overlay-1); }
.bank { margin:16px 0 6px; padding:14px; border:1px solid var(--border); border-radius:var(--radius); background:var(--bg-2); }
.bank-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.bank-head strong { display:block; color:var(--text); font-size:12.5px; font-weight:500; }
.bank-head span { display:block; margin-top:4px; color:var(--text-3); font-size:11px; }
.bank-empty { margin:12px 0 0; color:var(--text-3); font-size:11.5px; }
.bank-row { display:grid; grid-template-columns:26px minmax(0,1fr) 24px; align-items:center; gap:10px; margin-top:10px; }
.bank-meta { grid-column:2/-1; display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.bank-meta label { margin:0; }
.bank-index { color:var(--text-3); font-size:11px; }
.bank-remove { padding:0; border:0; background:transparent; color:var(--text-3); font-size:12px; cursor:pointer; }
.bank-remove:hover { color:var(--danger); }
.bank-stat { color:var(--text-3) !important; }

/* 场景库：工具栏 + 卡片网格 */
.listing { display: grid; gap: 16px; align-content: start; position: sticky; top: 16px; }
.listing-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.listing-head h2 { margin: 6px 0 0; }
.listing-count { margin: 0; color: var(--text-3); font-size: 12px; white-space: nowrap; }
.listing-count strong { color: var(--text); font-size: 15px; font-family: var(--font-num); }
.listing-count em { margin: 0 6px; font-style: normal; color: var(--border-bright); }
.toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; }
.toolbar .search { min-width: 0; }
.toolbar .sort { width: auto; min-width: 108px; color: var(--text-2); }
.seg { display: inline-flex; padding: 3px; border: 1px solid var(--border); border-radius: 999px; background: var(--bg-2); }
.seg button { padding: 5px 12px; border: 0; border-radius: 999px; background: transparent; color: var(--text-3); font-size: 12px; cursor: pointer; }
.seg button:hover { color: var(--text); }
.seg button.active { background: var(--panel-bg); color: var(--text); box-shadow: 0 1px 2px rgba(15,23,42,.08); }
.scene-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(206px, 1fr)); gap: 12px; }
.scene-card { display: grid; gap: 10px; padding: 16px 16px 12px; border: 1px solid var(--border); border-radius: 14px; background: var(--panel-bg); transition: border-color .16s var(--ease), box-shadow .16s var(--ease), transform .16s var(--ease); }
.scene-card:hover { border-color: var(--border-bright); box-shadow: 0 6px 18px rgba(15,23,42,.07); transform: translateY(-1px); }
.scene-card.off { background: var(--bg-2); }
.card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.pill { padding: 2px 8px; border-radius: 999px; background: var(--overlay-1); color: var(--text-2); font-size: 11px; }
.state { display: inline-flex; align-items: center; gap: 5px; color: var(--text-3); font-size: 11px; }
.state i { width: 6px; height: 6px; border-radius: 50%; background: #0f9d58; }
.state.off i { background: var(--border-bright); }
.scene-card h3 { margin: 0; color: var(--text); font-size: 15px; font-weight: 600; line-height: 1.45; letter-spacing: -.01em;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; word-break: break-word; }
.scene-card .meta { margin: 0; color: var(--text-3); font-size: 12px; line-height: 1.7; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); margin: 2px 0 0; padding-top: 10px; border-top: 1px solid var(--divider); }
.stats div { display: grid; gap: 2px; }
.stats dt { color: var(--text-3); font-size: 11px; }
.stats dd { margin: 0; color: var(--text); font-family: var(--font-num); font-size: 16px; }
.card-actions { display: flex; gap: 6px; justify-content: flex-end; }
.ghost { padding: 5px 12px; border: 1px solid transparent; border-radius: 999px; background: transparent; color: var(--text-2); font-size: 12px; cursor: pointer; }
.ghost:hover { background: var(--overlay-1); color: var(--text); }
.ghost.danger:hover { background: rgba(248,113,113,.1); color: #c2554a; }
.empty-line { margin: 8px 0; color: var(--text-3); font-size: 12px; }

/* 翻页 */
.pager { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 12px; border-top: 1px solid var(--divider); }
.pager-info { color: var(--text-3); font-size: 12px; white-space: nowrap; }
.pager-actions { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
.pager-btn { min-width: 30px; padding: 5px 10px; border: 1px solid transparent; border-radius: 999px; background: transparent; color: var(--text-2); font-size: 12px; cursor: pointer; }
.pager-btn:hover:not(:disabled) { background: var(--overlay-1); color: var(--text); }
.pager-btn.num { font-family: var(--font-num); }
.pager-pos { min-width: 52px; text-align: center; color: var(--text-2); font-size: 12px; }
.pager-btn:disabled { color: var(--border-bright); cursor: not-allowed; }
@media (max-width: 1180px) { .toolbar { grid-template-columns: minmax(0, 1fr) auto; } .toolbar .sort { grid-column: 1 / -1; width: 100%; } }
</style>
