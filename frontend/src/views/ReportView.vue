<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { useRoute } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'

import AnimatedNumber from '@/components/report/AnimatedNumber.vue'
import ScoreEvidencePanel from '@/components/report/ScoreEvidencePanel.vue'
import EvaluationQuality from '@/components/report/EvaluationQuality.vue'
import ReportSelfReview from '@/components/report/ReportSelfReview.vue'
import InterviewEvidencePanel from '@/components/report/InterviewEvidencePanel.vue'
import ScoreRadar from '@/components/report/ScoreRadar.vue'
import TrainingComparison from '@/components/report/TrainingComparison.vue'
import { useTrainingReport } from '@/composables/useTrainingReport'
import { useReportSharing } from '@/composables/useReportSharing'
import { reportAnswerTurns } from '@/lib/answerTurns'
import { api, errorMessage } from '@/lib/api'
import type { ApiEnvelope, Scores, TrainingSession } from '@/lib/types'

const route = useRoute()
const { evaluation, messages, session, error, rescoring, loadReport, rescore } = useTrainingReport(() => String(route.params.id))

interface Round { roundNo: number; question: string; answer: string; flags: readonly string[]; annotated: boolean }
const rounds = computed<Round[]>(() => {
  return reportAnswerTurns(session.value, messages.value).map(turn => ({
    roundNo: turn.roundNo, question: turn.question, answer: turn.answer, flags: turn.flags,
    annotated: Boolean(evaluation.value?.suggestions.some(item => item.roundNo === turn.roundNo)),
  }))
})
const deliveryAdvice = computed(() => {
  const raw = deliveryStats.value
  if (!raw) return [] as string[]
  const tips: string[] = []
  if (typeof raw.speechRate === 'number' && raw.speechRate > 260) tips.push('语速偏快（每分钟 ' + raw.speechRate + ' 字），关键信息容易被带过')
  else if (typeof raw.speechRate === 'number' && raw.speechRate < 120) tips.push('语速偏慢（每分钟 ' + raw.speechRate + ' 字），可以更紧凑一些')
  if (typeof raw.longestPause === 'number' && raw.longestPause >= 3) tips.push('最长停顿 ' + raw.longestPause + ' 秒，卡顿时可以用过渡句衔接')
  else if (typeof raw.pauseCount === 'number' && raw.pauseCount >= 6) tips.push('停顿 ' + raw.pauseCount + ' 次偏多，先想清结论再开口')
  if (typeof raw.fillerTotal === 'number' && raw.fillerTotal >= 5) tips.push('填充词 ' + raw.fillerTotal + ' 次，换成短停顿会更稳')
  return tips
})

const visionStats = computed(() => {
  const raw = (session.value?.delivery as { vision?: Record<string, unknown> } | undefined)?.vision
  if (!raw || raw.available === false) return null
  return raw as {
    faceRatio: number
    eyeContactRatio: number
    headStability: number
    brightness: number
    centerOffset: number
    tips?: string[]
  }
})


function replaySeek(seconds: number): void {
  const media = document.querySelector<HTMLMediaElement>('.training-compare video, .training-compare audio, .replay-media')
  if (!media) return
  media.currentTime = seconds
  void media.play().catch(() => undefined)
}

const deliveryStats = computed(() => {
  const raw = session.value?.delivery
  if (!raw || !raw.speechRate) return null
  return raw
})

// ③ 表达指标时间轴：停顿点落在录音的哪一秒，点击可跳转
const speechDuration = computed(() => {
  const raw = session.value?.delivery
  return Math.max(1, Math.round(session.value?.durationSeconds ?? raw?.durationSeconds ?? 0))
})

const pauseMarks = computed(() => {
  const pauses = (session.value?.delivery as unknown as { pauses?: Array<{ start: number; end: number; seconds: number }> } | undefined)?.pauses ?? []
  return pauses
    .filter((item) => item.seconds >= 0.6)
    .slice(0, 12)
    .map((item) => ({ ...item, percent: Math.min(100, (item.start / speechDuration.value) * 100) }))
})

// 同题横向对比：这道题以前怎么答的
interface SameQuestionAttempt { sessionId: string; startedAt: string; isCurrent: boolean; question: string; answer: string; overallScore: number | null; channel: string }
const attempts = shallowRef<Record<number, SameQuestionAttempt[]>>({})
const attemptsLoading = shallowRef<number | null>(null)

async function loadAttempts(roundNo: number): Promise<void> {
  if (attemptsLoading.value !== null) return
  attemptsLoading.value = roundNo
  try {
    const response = await api.get<ApiEnvelope<{ attempts: SameQuestionAttempt[] }>>(
      `/training-sessions/${route.params.id}/same-question/${roundNo}`,
    )
    attempts.value = { ...attempts.value, [roundNo]: response.data.data.attempts }
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    attemptsLoading.value = null
  }
}

// ① 行动计划：把报告里散落的建议压成三件事
interface PlannedAction { title: string; detail: string; label: string; to: RouteLocationRaw }
const weeklyActions = computed<PlannedAction[]>(() => {
  const current = evaluation.value
  if (!current) return []
  const actions: PlannedAction[] = []
  const weakest = [...DIMS].sort((a, b) => (current.scores[a] ?? 0) - (current.scores[b] ?? 0))[0]
  const evidence = current.evidence.find((item) => item.dimension === weakest)
  if (evidence) {
    actions.push({
      title: `先把「${labels[weakest]}」这一维拉起来`,
      detail: evidence.nextAction || evidence.reason || '按证据里的问题重写这一轮回答。',
      label: '去改这句',
      to: {
        name: 'scripts',
        query: {
          sceneId: session.value?.sceneId ?? '',
          original: evidence.quote,
          dimension: labels[weakest],
          objective: evidence.reason ?? '',
        },
      },
    })
  }
  const filler = current.speechStats?.topFillers?.[0]
  if (filler && filler.count >= 3) {
    actions.push({
      title: `这次只砍一个口头禅：「${filler.word}」`,
      detail: `本场出现 ${filler.count} 次。下一场刻意停顿 0.5 秒代替「${filler.word}」，比硬背稿有效。`,
      label: '再练一场',
      to: { name: 'scenes', query: { sceneId: session.value?.sceneId ?? '' } },
    })
  }
  const upgrade = current.upgrades?.[0]
  if (upgrade) {
    actions.push({
      title: '把一句空话换成一个具体结果',
      detail: `${upgrade.problem.replace(/。$/, '')}：${upgrade.original} → ${upgrade.improved}`,
      label: '看全部改写',
      to: { name: 'scripts', query: { sceneId: session.value?.sceneId ?? '', original: upgrade.original } },
    })
  }
  return actions.slice(0, 3)
})

// ② 逐题考察点：这一轮问的是什么维度、得分多少、证据里缺什么
function roundRubric(roundNo: number): { dimension: string; score: number; note: string } | null {
  const current = evaluation.value
  if (!current) return null
  const planned = session.value?.questionPlan?.[roundNo - 1]
  const evidence = current.evidence.find((item) => item.roundNo === roundNo)
  if (!planned && !evidence) return null
  const candidate = evidence?.dimension ?? planned?.dimension ?? ''
  const key = (Object.keys(labels).find((name) => labels[name as keyof Scores] === candidate) ?? candidate) as keyof Scores
  if (!(key in labels)) return null
  const dimension = labels[key] ?? evidence?.dimension ?? planned?.dimension ?? '综合表达'
  return {
    dimension: `${dimension}（整场维度参考）`,
    score: key in labels ? current.scores[key] : 0,
    note: evidence?.reason ?? '',
  }
}

const labels: Record<keyof Scores, string> = { logic: '内容与逻辑', relevance: '贴合问题', correctness: '信息完整', concision: '表达干净' }

const DIMS: Array<keyof Scores> = ['logic', 'relevance', 'correctness', 'concision']



// T-04：逐题 STAR 完整度（启发式，只做提示，不参与评分）
const STAR_PATTERNS: Array<[keyof StarCoverage, RegExp]> = [
  ['situation', /(当时|背景|项目|公司|团队|客户|业务|系统|平台|产品|部门|实习|学校|课程|比赛)/],
  ['task', /(负责|目标|需要|任务|要求|挑战|要解决|被安排|承担)/],
  ['action', /(我(先|做|通过|主导|设计|搭建|负责|改成|调整)|首先|然后|接着|于是|具体|办法|方案|优化|协调|排查|推进)/],
  ['result', /(结果|提升|降低|下降|完成|达成|最终|上线|节省|效率|从.{0,12}(到|降|升)|\d+\s*(%|倍|万|千|ms|秒|天|人))/],
]

interface StarCoverage { situation: boolean; task: boolean; action: boolean; result: boolean }

function starOf(answer: string): StarCoverage {
  return {
    situation: STAR_PATTERNS[0][1].test(answer),
    task: STAR_PATTERNS[1][1].test(answer),
    action: STAR_PATTERNS[2][1].test(answer),
    result: STAR_PATTERNS[3][1].test(answer),
  }
}

function isExperienceRound(roundNo: number): boolean {
  return evaluation.value?.questionTypes?.some((item) => item.roundNo === roundNo && item.type === 'EXPERIENCE') ?? false
}

function starScore(coverage: StarCoverage): number {
  return Object.values(coverage).filter(Boolean).length
}

function starHint(answer: string): string {
  const coverage = starOf(answer)
  const missing = [
    coverage.situation ? '' : '情境',
    coverage.task ? '' : '任务',
    coverage.action ? '' : '行动',
    coverage.result ? '' : '结果',
  ].filter(Boolean)
  return missing.length ? `缺${missing.join('、')}` : '四要素齐全'
}

const { shareBusy, openShareReport } = useReportSharing(() => session.value, message => { error.value = message })

// V-04：同场景两次录像并排对比
const compareSession = shallowRef<TrainingSession | null>(null)

async function loadCompare(): Promise<void> {
  const current = session.value
  if (!current?.recordingUrl) return
  try {
    const response = await api.get<ApiEnvelope<{ items?: TrainingSession[] } | TrainingSession[]>>('/training-sessions', { params: { size: 40 } })
    const payload = response.data.data
    const list = Array.isArray(payload) ? payload : (payload.items ?? [])
    const previous = list.find((item) => item.id !== current.id
      && item.sceneId === current.sceneId
      && item.channel === current.channel
      && Boolean(item.recordingUrl))
    if (!previous) return
    compareSession.value = previous
  } catch {
    // 对比是增强信息，取不到不影响报告
  }
}

// V-03：按题分段的录像片段
const segments = computed(() => session.value?.delivery?.segments ?? [])
const activeSegment = shallowRef(0)

function playSegment(index: number): void {
  activeSegment.value = index
  const player = document.querySelector<HTMLVideoElement>('.segment-player video')
  if (player) {
    player.load()
    void player.play().catch(() => undefined)
  }
}

// A-02：人工修正转写（视频/语音场次）
const editingRound = shallowRef<number | null>(null)
const editingText = shallowRef('')
const transcriptSaving = shallowRef(false)
const transcript = computed(() => session.value?.delivery?.transcript ?? [])
const needsRescore = computed(() => Boolean(session.value?.delivery?.rescoreRequired))

function startEdit(roundNo: number, text: string): void {
  editingRound.value = roundNo
  editingText.value = text
}

async function saveTranscript(roundNo: number): Promise<void> {
  if (!session.value || transcriptSaving.value) return
  transcriptSaving.value = true
  try {
    await api.patch(`/training-sessions/${session.value.id}/transcript/${roundNo}`, { text: editingText.value.trim() })
    editingRound.value = null
    await loadReport()
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    transcriptSaving.value = false
  }
}

function confidenceLabel(value: number | null): string {
  if (value === null || value === undefined) return '未提供置信度'
  if (value < 0.7) return `置信度 ${Math.round(value * 100)}% · 建议核对`
  return `置信度 ${Math.round(value * 100)}%`
}

const orderedScores = computed(() => evaluation.value
  ? DIMS.map((key) => [key, Number(evaluation.value!.scores[key]) || 0] as [keyof Scores, number])
    .sort((a, b) => b[1] - a[1])
  : [])
const weakestScore = computed(() => (orderedScores.value.length ? orderedScores.value[orderedScores.value.length - 1][1] : 0))

const overallDelta = computed(() => {
  const current = evaluation.value
  if (!current || current.overallScore === null || current.previousOverall === null || current.previousOverall === undefined) return null
  return Math.round((current.overallScore - current.previousOverall) * 10) / 10
})

function deltaOf(key: keyof Scores): number | null {
  const current = evaluation.value
  if (!current?.previousScores) return null
  const diff = current.scores[key] - current.previousScores[key]
  return diff === 0 ? 0 : diff
}

function deltaLabel(diff: number | null): string {
  if (diff === null) return ''
  if (diff === 0) return '持平'
  return diff > 0 ? `↑ ${Math.abs(diff)}` : `↓ ${Math.abs(diff)}`
}
const styleLine = computed(() => evaluation.value?.styleTags?.join(' · ') ?? '')
// 矛盾未消解时接口不给数字，页面直说原因，不显示 0 或空白。
const scoreNotice = computed(() => evaluation.value?.scoreUnavailableReason ?? null)


onMounted(async () => {
  try {
    await loadReport()
    await loadCompare()
  } catch (reason) { error.value = errorMessage(reason) }
})
</script>

<template>
  <div class="page report-page">
    <header class="report-head">
      <div class="head-copy">
        <p class="eyebrow">训练报告{{ session ? ' · ' + session.sceneTitle : '' }}</p>
        <h1>这一场，<br />哪里已经做对了？</h1>
        <p class="lead">评分是起点，不是结论。</p>
      </div>
      <div class="report-actions">
        <button type="button" class="button secondary" :disabled="shareBusy" @click="openShareReport">导出报告</button>

        <RouterLink class="button secondary" to="/scenes">再练一个</RouterLink>
      </div>
    </header>

    <div v-if="error" class="error-banner">{{ error }}</div>
    <div v-if="!evaluation && !error" class="skeleton report-loading" />

    <template v-if="evaluation">
      <EvaluationQuality :evaluation="evaluation" :pending="needsRescore" :rescoring="rescoring" @rescore="rescore" />
      <section class="hero">
        <div class="score">
          <p class="label">综合表现</p>
          <div v-if="evaluation.overallScore === null" class="figure figure-off">
            <span class="off">暂不可用</span>
          </div>
          <div v-else class="figure">
            <span class="num"><AnimatedNumber :value="evaluation.overallScore ?? 0" /></span>
            <span class="den">/ 100</span>
          </div>
          <p v-if="scoreNotice" class="score-notice">{{ scoreNotice }}</p>
          <p v-if="overallDelta !== null" class="overall-delta" :class="{ up: overallDelta > 0, down: overallDelta < 0 }">
            {{ overallDelta === 0 ? '与上次持平' : overallDelta > 0 ? `比上次高 ${overallDelta} 分` : `比上次低 ${Math.abs(overallDelta)} 分` }}
          </p>
          <p v-if="styleLine" class="style-line">{{ styleLine }}</p>
          <p v-if="evaluation.degraded" class="degraded">
            本报告由本地评分规则生成，未使用大模型语义评分。
            <button class="rescore" type="button" :disabled="rescoring" @click="rescore">
              {{ rescoring ? '重新评分中…' : '重新用大模型评分' }}
            </button>
          </p>
        </div>

        <div class="radar"><ScoreRadar :scores="evaluation.scores" /></div>

        <ul class="dims">
          <li v-if="scoreNotice" class="dims-note">四维分值为原记录值，仅作参考</li>
          <li v-for="([key, value], index) in orderedScores" :key="key" :class="{ weakest: value === weakestScore }">
            <span class="name">{{ labels[key] }}</span>
            <span class="bar"><b :style="{ '--w': `${value * 20}%`, animationDelay: `${index * 85}ms` }" /></span>
            <span class="val num">
              {{ value.toFixed(1) }}
              <i v-if="deltaOf(key) !== null" class="delta num" :class="{ up: (deltaOf(key) ?? 0) > 0, down: (deltaOf(key) ?? 0) < 0 }">{{ deltaLabel(deltaOf(key)) }}</i>
            </span>
          </li>
        </ul>
      </section>

      <section v-if="weeklyActions.length" class="actions-card panel">
        <header><h2>下一步怎么练</h2><span>按顺序做，别一次改所有问题</span></header>
        <ol>
          <li v-for="(action, index) in weeklyActions" :key="action.title">
            <span class="action-no num">0{{ index + 1 }}</span>
            <div>
              <strong>{{ action.title }}</strong>
              <p>{{ action.detail }}</p>
            </div>
            <RouterLink class="button secondary compact" :to="action.to">{{ action.label }}</RouterLink>
          </li>
        </ol>
      </section>

      <section class="summary">
        <p class="label">教练总评</p>
        <p class="summary-text">{{ evaluation.summary }}</p>
      </section>

      <ScoreEvidencePanel :evaluation="evaluation" />
      <InterviewEvidencePanel v-if="evaluation.assessment" :assessment="evaluation.assessment" />
      <section v-if="evaluation.technicalChecks?.length" class="panel">
        <h2>专业内容核查</h2>
        <article v-for="check in evaluation.technicalChecks" :key="check.roundNo + check.quote">
          <strong>第 {{ check.roundNo }} 轮 · {{ check.verdict === 'ERROR' ? '需纠正' : check.verdict === 'CORRECT' ? '判断正确' : '待核实' }}</strong>
          <p>原话：{{ check.quote }}</p><p>{{ check.reason }}</p>
        </article>
      </section>

      <section v-if="evaluation.riskFlags?.length" class="panel risk-panel">
        <h2>表达风险</h2>
        <ul class="risk-list">
          <li v-for="item in evaluation.riskFlags" :key="item">{{ item }}</li>
        </ul>
        <p class="risk-note">这些表达不计入分数，但容易让面试官感到被命令、被推责或过于绝对，下一场刻意避开。</p>
      </section>

      <section v-if="rounds.length" class="replay">
        <header class="replay-head">
          <h2>对话回放</h2>
          <span>{{ rounds.length }} 轮 · 有批注的轮次已标记</span>
        </header>
        <ol class="replay-list">
          <li v-for="round in rounds" :key="round.roundNo" class="replay-item" :class="{ flagged: round.annotated || round.flags.length }">
            <span class="replay-no num">第 {{ round.roundNo }} 轮</span>
            <div class="replay-body">
              <p class="replay-q">{{ round.question }}</p>
              <p class="replay-a">{{ round.answer }}</p>
              <p v-if="roundRubric(round.roundNo)" class="rubric-line">
                <span class="rubric-dim">考察 · {{ roundRubric(round.roundNo)?.dimension }}</span>
                <span v-if="roundRubric(round.roundNo)?.score" class="rubric-score">{{ roundRubric(round.roundNo)?.score }} / 5</span>
                <span v-if="roundRubric(round.roundNo)?.note" class="rubric-note">{{ roundRubric(round.roundNo)?.note }}</span>
              </p>
              <div v-if="isExperienceRound(round.roundNo)" class="star-row" :class="`star-${starScore(starOf(round.answer))}`">
                <span class="star-label">STAR {{ starScore(starOf(round.answer)) }}/4</span>
                <span v-for="key in (['situation','task','action','result'] as const)" :key="key" class="star-dot" :class="{ on: starOf(round.answer)[key] }">
                  {{ { situation: 'S', task: 'T', action: 'A', result: 'R' }[key] }}
                </span>
                <span class="star-hint">{{ starHint(round.answer) }}</span>
              </div>
              <p v-if="round.flags.length" class="replay-flags">表达提醒：{{ round.flags.join('、') }}</p>
              <div class="attempt-row">
                <button type="button" class="mini" :disabled="attemptsLoading === round.roundNo" @click="loadAttempts(round.roundNo)">
                  {{ attemptsLoading === round.roundNo ? '查找中…' : attempts[round.roundNo] ? '重新对比' : '同题对比' }}
                </button>
                <span v-if="attempts[round.roundNo]" class="attempt-hint">
                  {{ attempts[round.roundNo].length ? `共 ${attempts[round.roundNo].length} 次历史作答` : '还没有历史作答' }}
                </span>
              </div>
              <div v-if="attempts[round.roundNo]" class="attempt-list">
                <article v-for="attempt in attempts[round.roundNo]" :key="attempt.sessionId + attempt.startedAt" class="attempt-item" :class="{ current: attempt.isCurrent }">
                  <header>
                    <span>{{ new Date(attempt.startedAt).toLocaleDateString('zh-CN') }}</span>
                    <span v-if="attempt.isCurrent" class="tag">本次</span>
                    <strong v-if="attempt.overallScore !== null" class="num">{{ attempt.overallScore }} 分</strong>
                    <span v-if="isExperienceRound(round.roundNo)" class="star-label">STAR {{ starScore(starOf(attempt.answer)) }}/4</span>
                  </header>
                  <p>{{ attempt.answer }}</p>
                  <p class="attempt-missing"><template v-if="isExperienceRound(round.roundNo)">{{ starHint(attempt.answer) }} · </template>{{ attempt.answer.length }} 字</p>
                </article>
              </div>
            </div>
          </li>
        </ol>
      </section>


      <TrainingComparison
        v-if="session"
        :session-id="session.id"
        :current-url="session.recordingUrl ?? null"
        :previous-url="compareSession?.recordingUrl ?? null"
        :channel="session.channel"
      />

      <section v-if="segments.length" class="segments panel">
        <header><h2>按题回看</h2><span>每段只包含该题的回答，可逐题复盘</span></header>
        <ol class="segment-tabs">
          <li v-for="(segment, index) in segments" :key="segment.roundNo">
            <button type="button" :class="{ active: index === activeSegment }" @click="playSegment(index)">
              第 {{ segment.roundNo }} 题
            </button>
          </li>
        </ol>
        <div class="segment-player">
          <video :src="segments[activeSegment]?.url ?? undefined" controls preload="metadata" />
          <p>{{ segments[activeSegment]?.question }}</p>
        </div>
      </section>

      <section v-if="transcript.length" class="transcript panel">
        <header>
          <h2>转写文本</h2>
          <span>识别有误可以手动改，改完需要重新评分</span>
        </header>
        <p v-if="needsRescore" class="rescore-tip">
          转写已修改，当前报告基于旧文本。
          <button type="button" class="rescore" :disabled="rescoring" @click="rescore">{{ rescoring ? '重新评分中…' : '用新文本重新评分' }}</button>
        </p>
        <ul>
          <li v-for="item in transcript" :key="item.roundNo">
            <div class="tr-head">
              <span class="num">第 {{ item.roundNo }} 轮</span>
              <span class="tr-conf" :class="{ low: item.confidence !== null && item.confidence < 0.7 }">{{ confidenceLabel(item.confidence) }}</span>
              <button v-if="editingRound !== item.roundNo" type="button" class="mini" @click="startEdit(item.roundNo, item.text)">修正</button>
            </div>
            <p class="tr-q">{{ item.question }}</p>
            <template v-if="editingRound === item.roundNo">
              <textarea v-model="editingText" class="field" rows="3" maxlength="2000" />
              <div class="tr-actions">
                <button class="button" type="button" :disabled="transcriptSaving" @click="saveTranscript(item.roundNo)">{{ transcriptSaving ? '保存中…' : '保存修正' }}</button>
                <button class="button secondary" type="button" @click="editingRound = null">取消</button>
              </div>
            </template>
            <p v-else class="tr-text">{{ item.text }}<span v-if="item.edited" class="tr-edited">已人工修正</span></p>
          </li>
        </ul>
      </section>

      <ReportSelfReview :session="session" :rounds="rounds" @error="error = $event" />

      <details v-if="deliveryStats || session?.jobMatch || visionStats" class="more-panel panel">
        <summary>
          <span>更多分析</span>
          <em>表达节奏 · 岗位匹配 · 镜头表现</em>
        </summary>

        <section v-if="deliveryStats" class="speech panel">
        <header class="speech-head"><h2>表达节奏</h2><span>基于本场语音的停顿与语速分析</span></header>
        <dl class="speech-grid">
          <div><dt>语速</dt><dd class="num">{{ deliveryStats.speechRate }}<small>字/分</small></dd></div>
          <div><dt>净语速</dt><dd class="num">{{ deliveryStats.articulationRate }}<small>字/分</small></dd></div>
          <div><dt>停顿</dt><dd class="num">{{ deliveryStats.pauseCount }}<small>次</small></dd></div>
          <div><dt>最长停顿</dt><dd class="num">{{ deliveryStats.longestPause }}<small>秒</small></dd></div>
        </dl>
        <p v-if="deliveryAdvice.length" class="delivery-advice">
          <span v-for="tip in deliveryAdvice" :key="tip">{{ tip }}</span>
        </p>
        <p class="speech-tags">
          <span class="tag">开口 {{ deliveryStats.durationSeconds }} 秒</span>
          <span class="tag">说话 {{ deliveryStats.charCount }} 字</span>
          <span v-if="deliveryStats.fillerTotal" class="tag">填充词 {{ deliveryStats.fillerTotal }} 次</span>
        </p>
        <div v-if="pauseMarks.length && session?.recordingUrl" class="pause-timeline">
          <div class="timeline-head">
            <span>停顿分布</span>
            <span>{{ pauseMarks.length }} 处 ≥ 0.6 秒 · 点击跳到录音位置</span>
          </div>
          <div class="timeline-track">
            <i
              v-for="(mark, index) in pauseMarks"
              :key="index"
              class="pause-mark"
              :style="{ left: `${mark.percent}%`, height: `${Math.min(72, 18 + mark.seconds * 12)}px` }"
              :title="`${mark.start.toFixed(1)}s 停顿 ${mark.seconds.toFixed(1)}s`"
              @click="replaySeek(mark.start)"
            />
          </div>
          <div class="timeline-scale"><span>0s</span><span>{{ speechDuration }}s</span></div>
        </div>
        </section>

        <section v-if="session?.jobMatch" class="speech panel">
        <header class="speech-head">
          <h2>岗位匹配</h2>
          <span>{{ session.jobMatch.score }} / 100 · {{ session.jobMatch.degraded ? '规则估算' : '按 JD 与简历对比' }}</span>
        </header>
        <ul v-if="session.jobMatch.strengths.length" class="match-list">
          <li v-for="item in session.jobMatch.strengths" :key="item"><b>优势</b>{{ item }}</li>
        </ul>
        <ul v-if="session.jobMatch.gaps.length" class="match-list">
          <li v-for="gap in session.jobMatch.gaps" :key="gap.requirement">
            <b>缺口</b>{{ gap.requirement }} — {{ gap.why }}
            <em>{{ gap.drill }}</em>
          </li>
        </ul>
        </section>



        <section v-if="visionStats" class="speech panel">
        <header class="speech-head"><h2>镜头表现</h2><span>画面里的客观指标，不评价长相</span></header>
        <dl class="speech-grid">
          <div><dt>出镜率</dt><dd class="num">{{ Math.round(visionStats.faceRatio * 100) }}<small>%</small></dd></div>
          <div><dt>看镜头</dt><dd class="num">{{ Math.round(visionStats.eyeContactRatio * 100) }}<small>%</small></dd></div>
          <div><dt>头部稳定</dt><dd class="num">{{ Math.round(visionStats.headStability * 100) }}<small>%</small></dd></div>
          <div><dt>画面亮度</dt><dd class="num">{{ Math.round(visionStats.brightness) }}<small>/255</small></dd></div>
        </dl>
        <p v-if="visionStats.tips?.length" class="delivery-advice">
          <span v-for="tip in visionStats.tips" :key="tip">{{ tip }}</span>
        </p>
        </section>



      </details>

      <section v-if="evaluation.suggestions.length" class="suggestions">
        <header class="section-head">
          <h2 class="label">改写建议</h2>
          <span class="note">{{ evaluation.suggestions.length }} 处</span>
        </header>
        <article v-for="(suggestion, index) in evaluation.suggestions" :key="`${suggestion.roundNo}-${index}`" class="suggestion">
          <span class="idx num">{{ String(index + 1).padStart(2, '0') }}</span>
          <div class="suggestion-body">
            <h3>{{ suggestion.problem }}</h3>
            <div class="compare">
              <div class="quote">
                <span>原表达</span>
                <p>{{ suggestion.original || '未记录原文' }}</p>
              </div>
              <div class="quote rewrite">
                <span>建议改写</span>
                <p>{{ suggestion.rewrite }}</p>
              </div>
              <div v-if="suggestion.reference" class="quote reference">
                <span>满分回答</span>
                <p>{{ suggestion.reference }}</p>
              </div>
            </div>
            <RouterLink
              class="deep-link"
              :to="{ name: 'scripts', query: { sceneId: session?.sceneId, original: suggestion.original || '', objective: suggestion.problem } }"
            >在话术优化里深入改写 →</RouterLink>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.report-page { max-width: 1080px; }
.report-loading { min-height: 520px; }

.hero {
  display: grid;
  grid-template-columns: minmax(0, .8fr) 240px minmax(0, 1.15fr);
  align-items: center;
  gap: 44px 46px;
  padding: 40px 44px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel-bg);
}
.score { display: flex; flex-direction: column; }
.overall-delta { margin: 8px 0 0; color: var(--text-3); font-size: 12px; }
.overall-delta.up { color: var(--success); }
.overall-delta.down { color: var(--danger); }
.delta { color: var(--text-3); font-size: 10px; font-style: normal; margin-left: 4px; }
.label { margin: 0; color: var(--text-3); font-size: 11px; letter-spacing: .2em; }
.figure { display: flex; align-items: flex-end; gap: 12px; margin-top: 18px; }
.figure .num {
  color: var(--text);
  font-family: var(--font-num);
  font-size: 92px;
  font-weight: 200;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.05em;
  line-height: .8;
}
.figure .den { padding-bottom: 9px; color: var(--text-3); font-family: var(--font-num); font-size: 12px; letter-spacing: .06em; }
.style-line { margin: 24px 0 0; color: var(--text-2); font-size: 13px; line-height: 1.9; letter-spacing: .04em; }
.figure-off { align-items: baseline; }
.figure-off .off { color: var(--warning); font-family: var(--font-num); font-size: 44px; font-weight: 200; letter-spacing: .02em; }
.score-notice { max-width: 34ch; margin: 14px 0 0; color: var(--warning); font-size: 12px; line-height: 1.8; }
.dims .dims-note { display: block; padding: 0 0 10px; border-bottom: 1px solid var(--divider); color: var(--text-3); font-size: 11px; letter-spacing: .04em; }
.risk-panel h2 { margin: 0; font-size: 13px; font-weight: 500; color: var(--text-2); letter-spacing: .04em; }
.risk-list { list-style: none; margin: 14px 0 0; padding: 0; display: grid; gap: 8px; }
.risk-list li { display: inline-flex; width: fit-content; padding: 3px 10px; border: 1px solid var(--border); border-radius: 999px; color: var(--text-2); font-size: 12px; }
.risk-note { margin: 12px 0 0; color: var(--text-3); font-size: 11.5px; line-height: 1.75; }
.degraded { margin: 12px 0 0; color: var(--warning); font-size: 11px; line-height: 1.7; }
.rescore { margin-left: 8px; padding: 2px 10px; border: 1px solid var(--border-bright); border-radius: 999px; background: transparent; color: var(--text-2); font-size: 11px; cursor: pointer; }
.rescore:hover:not(:disabled) { border-color: var(--accent); color: var(--accent-strong); }

.radar { display: flex; justify-content: center; }

.dims { display: flex; flex-direction: column; width: 100%; max-width: 340px; justify-self: end; margin: 0; padding: 0; list-style: none; }
.dims .val { display: inline-flex; align-items: baseline; justify-content: flex-end; gap: 3px; white-space: nowrap; }
.dims li {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr) 92px;
  align-items: center;
  gap: 14px;
  padding: 13px 0;
  border-bottom: 1px solid var(--divider);
}
.dims li:last-child { border-bottom: 0; }
.dims .name { color: var(--text-3); font-size: 12px; letter-spacing: .04em; white-space: nowrap; }
.dims .bar { position: relative; height: 3px; border-radius: 999px; background: var(--track); overflow: hidden; }
.dims .bar b { position: absolute; inset: 0 auto 0 0; background: var(--fill); }
.dims .val { color: var(--text); font-family: var(--font-num); font-size: 14px; text-align: right; }
.dims li.weakest .name { color: var(--text); }
.dims li.weakest .bar b { background: var(--accent); }

.summary { margin-top: 42px; padding-top: 18px; border-top: 1px solid var(--divider); }
.summary-text { max-width: 76ch; margin: 16px 0 0; color: var(--text-2); font-size: 15px; line-height: 2; letter-spacing: .01em; }

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 15px;
  border-bottom: 1px solid var(--divider);
}
.section-head h2 { margin: 0; color: var(--text-3); font-size: 11px; font-weight: 400; letter-spacing: .2em; }
.section-head .note { color: var(--text-3); font-size: 11px; letter-spacing: .06em; }

.speech { margin-top: 42px; padding: 22px 24px; }
.speech-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }
.speech-head h2 { margin: 0; font-size: 13px; font-weight: 500; color: var(--text-2); letter-spacing: .04em; }
.speech-head span { color: var(--text-3); font-size: 11px; }
.speech-grid { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 20px; margin: 18px 0 0; }
.speech-grid dt { color: var(--text-3); font-size: 11px; letter-spacing: .12em; }
.speech-grid dd { margin: 8px 0 0; color: var(--text); font-size: 22px; font-weight: 300; font-family: var(--font-num); }
.speech-grid small { margin-left: 4px; color: var(--text-3); font-size: 11px; }
.delivery-advice { margin: 6px 0 0; display: grid; gap: 6px; color: var(--text-2); font-size: 12.5px; line-height: 1.7; }
.speech-tags { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 0; }
.speech-tags span { padding: 3px 8px; border: 1px solid var(--border); border-radius: 4px; color: var(--text-2); font-size: 11.5px; }
.replay { margin-top: 42px; }
.replay-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--divider); }
.replay-head h2 { margin: 0; color: var(--text); font-size: 14px; font-weight: 500; }
.replay-head span { color: var(--text-3); font-size: 11px; }
.replay-list { margin: 0; padding: 0; list-style: none; }
.replay-item { display: grid; grid-template-columns: 62px minmax(0,1fr); gap: 14px; padding: 14px 0; border-bottom: 1px solid var(--divider); }
.replay-no { color: var(--text-3); font-size: 11px; padding-top: 2px; }
.replay-item.flagged .replay-no { color: var(--accent-strong); }
.replay-q { margin: 0; color: var(--text-2); font-size: 12.5px; line-height: 1.8; }
.replay-a { margin: 6px 0 0; color: var(--text); font-size: 13px; line-height: 1.9; white-space: pre-wrap; }
.replay-item.flagged .replay-a { border-left: 2px solid var(--accent); padding-left: 10px; margin-left: -12px; }
.replay-flags { margin: 6px 0 0; color: var(--warning); font-size: 11px; }
.suggestions { margin-top: 42px; }
.suggestion {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 18px;
  padding: 24px 0;
  border-bottom: 1px solid var(--divider);
}
.suggestion .idx { color: var(--text-3); font-family: var(--font-num); font-size: 11px; letter-spacing: .08em; }
.suggestion h3 { margin: 0 0 16px; color: var(--text); font-size: 15px; font-weight: 500; letter-spacing: .01em; line-height: 1.6; }

.compare { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
.quote { padding-left: 16px; border-left: 1px solid var(--border-bright); }
.quote.reference { grid-column: 1 / -1; border-left: 2px solid var(--accent); }
.quote.reference span { color: var(--accent-strong); }
.quote.rewrite { border-left: 1px solid var(--accent); }
.quote span { display: block; color: var(--text-3); font-size: 11px; letter-spacing: .14em; }
.quote p { margin: 9px 0 0; color: var(--text-2); font-size: 13px; line-height: 1.85; white-space: pre-wrap; }
.quote.rewrite p { color: var(--text); }
.dims .delta.up { color: var(--success); }
.dims .delta.down { color: var(--danger); }
.delta.num { font-size: 11px; }

/* 进度条：入场时从 0 长到目标值 */
.bar b {
  width: 0;
  animation: bar-grow .62s cubic-bezier(.22, .8, .28, 1) both;
}
@keyframes bar-grow {
  from { width: 0; }
  to { width: var(--w); }
}
@media (prefers-reduced-motion: reduce) {
  .bar b { animation: none; width: var(--w); }
}
.stability-note { margin: 8px 0 0; color: var(--text-3); font-size: 12px; }
.reference-text { margin: 8px 0 0; color: var(--text-2); line-height: 1.9; font-size: 13.5px; }
.replay-media { width: 100%; margin-top: 6px; border-radius: 10px; }
.mark-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.mark-row button { padding: 5px 11px; border: 1px solid var(--border); border-radius: 999px; background: var(--bg-2); color: var(--text-2); font-size: 12px; cursor: pointer; }
.mark-row button:hover { border-color: var(--accent); color: var(--accent-strong); }

.report-actions { display: flex; gap: 10px; }
.suggestion .deep-link { display: inline-block; margin-top: 14px; color: var(--accent-strong); font-size: 12px; letter-spacing: .02em; }
.match-list { list-style: none; margin: 6px 0 0; padding: 0; display: grid; gap: 8px; }
.match-list li { color: var(--text-2); font-size: 12.5px; line-height: 1.8; }
.match-list b { margin-right: 8px; color: var(--text-3); font-weight: 500; font-size: 11.5px; }
.match-list em { display: block; color: var(--accent-strong); font-style: normal; font-size: 12px; }
.compare.panel { display: grid; grid-template-columns: 1fr; padding: 22px; }
.compare-body { display: grid; gap: 20px; width: 100%; }
.compare-radars { display: flex; justify-content: center; gap: 120px; flex-wrap: wrap; }
.compare-radar { width: 240px; text-align: center; }
.compare-label { margin: 0 0 4px; color: var(--text-3); font-size: 12px; }
.compare-label.now { color: var(--accent-strong); font-weight: 600; }
.compare-rows { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; width: fit-content; margin-inline: auto; }
.compare-rows li { display: grid; grid-template-columns: 84px 92px 40px; align-items: center; gap: 14px; font-size: 12.5px; }
.compare-rows .label { color: var(--text-3); }
.compare-rows .delta { text-align: right; color: var(--text-3); }
.compare-rows .delta.up { color: var(--success); }
.compare-rows .delta.down { color: var(--danger); }
@media print {
  .app-shell aside, .app-shell header, .report-actions, .mark-row, .replay-media,
  .speech.panel:has(.mark-row), button { display: none !important; }
  .page, .report { padding: 0 !important; max-width: none !important; }
  .panel { break-inside: avoid; box-shadow: none !important; border-color: #ccc !important; }
}

.star-row { display: flex; align-items: center; gap: 6px; margin-top: 8px; }
.star-label { color: var(--text-3); font-size: 11px; letter-spacing: .04em; }
.star-dot { display: inline-grid; place-items: center; width: 18px; height: 18px; border: 1px solid var(--border); border-radius: 50%; color: var(--text-3); font-size: 10px; }
.star-dot.on { border-color: var(--accent); color: var(--accent-strong); background: var(--accent-soft); }
.star-hint { color: var(--text-3); font-size: 11px; }


.transcript header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.transcript header span { color: var(--text-3); font-size: 11.5px; }
.transcript ul { list-style: none; margin: 12px 0 0; padding: 0; display: grid; gap: 12px; }
.transcript li { padding: 12px 14px; border: 1px solid var(--border); border-radius: 8px; }
.tr-head { display: flex; align-items: center; gap: 10px; }
.tr-head .num { color: var(--text-3); font-size: 11.5px; }
.tr-conf { margin-left: auto; color: var(--text-3); font-size: 11px; }
.tr-conf.low { color: var(--error, #b4553f); }
.tr-q { margin: 8px 0 4px; color: var(--text-3); font-size: 12px; }
.tr-text { margin: 0; color: var(--text-2); font-size: 13px; line-height: 1.8; }
.tr-edited { margin-left: 8px; color: var(--accent-strong); font-size: 11px; }
.tr-actions { display: flex; gap: 8px; margin-top: 8px; }
.mini { padding: 2px 8px; border: 1px solid var(--border); border-radius: 999px; background: transparent; color: var(--text-2); font-size: 11px; cursor: pointer; }
.rescore-tip { margin: 10px 0 0; color: var(--warning); font-size: 12px; }

.segments header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.segments header span { color: var(--text-3); font-size: 11.5px; }
.segment-tabs { list-style: none; margin: 12px 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
.segment-tabs button { padding: 5px 12px; border: 1px solid var(--border); border-radius: 999px; background: var(--card); color: var(--text-2); font-size: 12px; cursor: pointer; }
.segment-tabs button.active { border-color: var(--accent); color: var(--accent-strong); background: var(--accent-soft); }
.segment-player video { width: 100%; max-height: 46vh; border-radius: 10px; background: #0b0b0e; }
.segment-player p { margin: 8px 0 0; color: var(--text-3); font-size: 12px; }



.actions-card header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.actions-card header span { color: var(--text-3); font-size: 11.5px; }
.actions-card ol { list-style: none; margin: 12px 0 0; padding: 0; display: grid; gap: 12px; }
.actions-card li { display: grid; grid-template-columns: 30px minmax(0, 1fr) auto; gap: 12px; align-items: start; padding-top: 12px; border-top: 1px solid var(--divider); }
.actions-card li:first-child { border-top: 0; padding-top: 0; }
.action-no { color: var(--accent-strong); font-size: 12px; padding-top: 2px; }
.actions-card strong { display: block; color: var(--text); font-size: 13.5px; font-weight: 600; }
.actions-card p { margin: 4px 0 0; color: var(--text-2); font-size: 12.5px; line-height: 1.75; }
.rubric-line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; margin: 8px 0 0; font-size: 11.5px; }
.rubric-dim { padding: 2px 8px; border: 1px solid var(--border); border-radius: 999px; color: var(--text-2); }
.rubric-score { color: var(--text); font-variant-numeric: tabular-nums; }
.rubric-note { color: var(--text-3); }
.pause-timeline { margin-top: 14px; }
.timeline-head { display: flex; justify-content: space-between; color: var(--text-3); font-size: 11.5px; }
.timeline-track { position: relative; height: 26px; margin: 6px 0 2px; border-radius: 4px; background: linear-gradient(90deg, var(--track), var(--track)); }
.pause-mark { position: absolute; bottom: 2px; width: 3px; border-radius: 2px; background: var(--accent); cursor: pointer; transition: opacity .14s var(--ease); }
.pause-mark:hover { opacity: .65; }
.timeline-scale { display: flex; justify-content: space-between; color: var(--text-3); font-size: 10.5px; }

.attempt-row { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.attempt-hint { color: var(--text-3); font-size: 11px; }
.attempt-list { display: grid; gap: 8px; margin-top: 10px; }
.attempt-item { padding: 10px 12px; border: 1px solid var(--border); border-left: 2px solid var(--border); border-radius: 0 8px 8px 0; background: var(--bg-2); }
.attempt-item.current { border-left-color: var(--accent); }
.attempt-item header { display: flex; align-items: baseline; gap: 10px; color: var(--text-3); font-size: 11px; }
.attempt-item header .tag { padding: 1px 6px; border: 1px solid var(--accent); border-radius: 999px; color: var(--accent-strong); font-size: 10px; }
.attempt-item header strong { margin-left: auto; color: var(--text); font-size: 12.5px; }
.attempt-item p { margin: 6px 0 0; color: var(--text-2); font-size: 12.5px; line-height: 1.75; }
.attempt-item .attempt-missing { color: var(--text-3); font-size: 11px; }
</style>
<style scoped>
.report-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 30px; }
.report-head h1 { margin: 10px 0 0; font-size: clamp(28px, 3.2vw, 38px); font-weight: 650; letter-spacing: -.02em; line-height: 1.25; }
.report-head .lead { margin: 12px 0 0; color: var(--text-3); font-size: 14px; }
.report-actions { display: flex; gap: 8px; flex: none; flex-wrap: wrap; }
.hero { padding: 34px 38px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel-bg); }
.hero .label { font-size: 12.5px; color: var(--text-3); }
.summary { margin-top: 32px; }
.summary .label { font-size: 12.5px; color: var(--text-3); }
.summary-text { margin: 10px 0 0; max-width: 76ch; color: var(--text); font-size: 15px; line-height: 1.95; }
.replay { margin-top: 40px; }
.replay-head h2, .segments h2, .transcript h2, .self-review h2, .suggestions h2, .more-panel summary span { font-size: 18px; font-weight: 600; }
.replay-head span, .segments header span, .transcript header span, .self-review header span { display: none; }
.replay-item { padding: 18px 0; }
.replay-q { color: var(--text-3); font-size: 13px; }
.replay-a { font-size: 14.5px; line-height: 1.8; }
.more-panel { margin-top: 36px; padding: 0; border-top: 1px solid var(--divider); background: transparent; }
.more-panel summary { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; padding: 18px 0; cursor: pointer; list-style: none; }
.more-panel summary::-webkit-details-marker { display: none; }
.more-panel summary em { font-style: normal; color: var(--text-3); font-size: 12.5px; }
.more-panel[open] summary { border-bottom: 1px solid var(--divider); margin-bottom: 0; }
/* 每块独立成卡：沿用 .panel 的描边与圆角，块之间用留白隔开而不是分割线 */
.more-panel > .speech,
.more-panel > .compare { margin-top: 24px; padding: 28px 32px; }
.more-panel > section:last-child { margin-bottom: 12px; }
.more-panel .speech-head h2 { font-size: 17px; letter-spacing: .01em; }
.more-panel .speech-head span { display: none; }
.more-panel .speech-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); column-gap: 24px; row-gap: 28px; margin: 22px 0 0; }
.more-panel .speech-grid dt { font-size: 11.5px; }
.more-panel .speech-grid dd { margin: 10px 0 0; font-size: 32px; line-height: 1.1; }
.more-panel .speech-grid small { margin-left: 8px; font-size: 13px; }
.more-panel .delivery-advice { margin: 20px 0 0; gap: 8px; font-size: 12.5px; line-height: 1.8; }
.more-panel .speech-tags { margin: 20px 0 0; gap: 10px; line-height: 1.6; }
.more-panel .speech-tags span { line-height: 1.6; }
.more-panel .match-list { margin: 16px 0 0; gap: 10px; }
.more-panel .match-list li { line-height: 1.8; }
.more-panel .upgrade-list { margin: 16px 0 0; gap: 16px; }
.more-panel .reference-text { margin: 16px 0 0; font-size: 13px; line-height: 1.9; }
.more-panel .pause-timeline { margin-top: 24px; }
.more-panel .timeline-head { flex-direction: column; align-items: flex-start; gap: 4px; font-size: 12.5px; line-height: 1.6; }
.more-panel .timeline-track { height: 90px; margin: 12px 0 0; border-radius: 8px; }
.more-panel .pause-mark { border-radius: 2px 2px 0 0; }
.more-panel .timeline-scale { margin-top: 8px; font-size: 12.5px; }
.more-panel .compare-body { gap: 28px; }
@media (max-width: 1199px) {
  .more-panel .speech-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .more-panel > .speech, .more-panel > .compare { padding: 24px 20px; }
}
.suggestions { margin-top: 40px; }
</style>
