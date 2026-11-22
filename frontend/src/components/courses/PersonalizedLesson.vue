<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, shallowRef, useTemplateRef } from 'vue'
import CartoonPresenter from '@/components/media/CartoonPresenter.vue'

import { api, errorMessage, MODEL_REQUEST_TIMEOUT_MS } from '@/lib/api'
import type { ApiEnvelope, LessonResponse, LessonVideoState, TrainingPlan, TrainingPlanTask } from '@/lib/types'

const props = defineProps<{
  plan: TrainingPlan
  task: TrainingPlanTask
  submitting: boolean
}>()
const emit = defineEmits<{ completeCourse: []; completeStep: [index: number]; submitPractice: [answer: string] }>()

const POLL_VISIBLE_MS = 3000
const POLL_HIDDEN_MS = 10000

const generated = shallowRef<LessonResponse | null>(null)
const lessonGenerating = shallowRef(true)
const lessonError = shallowRef('')
const videoUrl = shallowRef('')
const videoState = shallowRef<LessonVideoState | null>(null)
const stateLoading = shallowRef(true)
const stateError = shallowRef('')
const chapters = shallowRef<Array<{ title: string; start: number; duration: number }>>([])
const videoEl = shallowRef<HTMLVideoElement | null>(null)
const activeChapter = shallowRef(0)
const watched = shallowRef(0)
const duration = shallowRef(0)
// 微课虚拟形象暂时下线（用户要求先停掉），代码保留，改回 true 即可恢复
const TEACHER_ENABLED = false
const teacher = useTemplateRef<InstanceType<typeof CartoonPresenter>>('teacher')
const teacherConfigured = shallowRef(false)
const teacherVisible = shallowRef(true)
const teacherMode = shallowRef(false)
const teacherSpeaking = shallowRef(false)
const teacherListening = shallowRef(false)
const teacherError = shallowRef('')
const pageVisible = shallowRef(true)
let lectureAudio: AudioContext | null = null
let lectureSource: MediaElementAudioSourceNode | null = null
let lectureAnalyser: AnalyserNode | null = null

let pollTimer: ReturnType<typeof setTimeout> | null = null
const requests = new AbortController()

const lesson = computed(() => generated.value?.lesson ?? props.task.lesson)
const courseTitle = computed(() => lesson.value?.title ?? '沟通微课')
const progress = computed(() => props.task.learningProgress ?? 0)
const practice = shallowRef('')
const canFinish = computed(() => Boolean(lesson.value) && props.task.completedSteps.length === lesson.value?.steps.length && !props.task.learned && !props.task.completed)
const watchedPercent = computed(() => (duration.value > 0 ? Math.min(100, Math.round((watched.value / duration.value) * 100)) : 0))

const videoStatus = computed(() => videoState.value?.status ?? '')
const generating = computed(() => videoStatus.value === 'PENDING' || videoStatus.value === 'RUNNING')
const jobProgress = computed(() => Math.max(0, Math.min(100, Math.round(videoState.value?.progress ?? 0))))
const stageText = computed(() => {
  const stage = videoState.value?.stage?.trim()
  if (stage) return stage
  return videoStatus.value === 'PENDING' ? '已排入生成队列，马上开始' : '正在渲染色讲画面'
})
const failureText = computed(() => (videoStatus.value === 'FAILED' ? videoState.value?.error?.trim() || '视频生成失败，请重新生成' : ''))
const videoPath = computed(() => '/training-plans/' + props.plan.id + '/lesson/video')

function mediaUrl(url: string): string {
  return (import.meta.env.VITE_API_BASE ?? '/api/v1').replace('/api/v1', '') + url
}

function routeLectureAudio(): void {
  const element = videoEl.value
  if (!element || !lectureAudio) return
  if (lectureSource?.mediaElement !== element) {
    lectureSource?.disconnect()
    lectureAnalyser?.disconnect()
    lectureSource = lectureAudio.createMediaElementSource(element)
    lectureAnalyser = lectureAudio.createAnalyser()
    lectureAnalyser.fftSize = 256
    lectureSource.connect(lectureAnalyser)
    lectureAnalyser.connect(lectureAudio.destination)
  }
  teacher.value?.observeAudio(teacherMode.value ? lectureAnalyser : null)
}

async function onPlay(): Promise<void> {
  if (!teacherVisible.value || !teacherConfigured.value || !videoEl.value) return
  const element = videoEl.value
  teacherError.value = ''
  try {
    lectureAudio ??= new AudioContext()
    await lectureAudio.resume()
    const connected = await teacher.value?.connect()
    if (requests.signal.aborted || element !== videoEl.value || element.paused || !teacherVisible.value) return
    teacherMode.value = Boolean(connected)
    routeLectureAudio()
    teacherSpeaking.value = teacherMode.value
  } catch {
    teacherMode.value = false
    teacherSpeaking.value = false
    teacher.value?.finishAudio()
    teacherError.value = '动态老师音频暂不可用，已切换课件原声'
  }
}

function onPause(): void {
  teacherSpeaking.value = false
  teacher.value?.finishAudio()
}

// 学生在写练习时，卡通老师切到倾听状态
function onPracticeFocus(): void { teacherListening.value = true }
function onPracticeBlur(): void { teacherListening.value = false }

function onTeacherConfigured(value: boolean): void {
  teacherConfigured.value = value
  if (value && teacherVisible.value && videoEl.value && !videoEl.value.paused) void onPlay()
}

function onSeeking(): void {
  onPause()
}

function onSeeked(): void {
  if (videoEl.value && !videoEl.value.paused) void onPlay()
}

function toggleTeacher(): void {
  teacherVisible.value = !teacherVisible.value
  if (!teacherVisible.value) {
    teacherMode.value = false
    onPause()
  } else if (videoEl.value && !videoEl.value.paused) {
    void onPlay()
  }
}

function clearPoll(): void {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

// 可见时 3s、页面隐藏时 10s 轮询生成进度，完成后自然停表
function schedulePoll(): void {
  clearPoll()
  if (!generating.value) return
  pollTimer = setTimeout(() => { void refreshState() }, pageVisible.value ? POLL_VISIBLE_MS : POLL_HIDDEN_MS)
}

function onVisibilityChange(): void {
  pageVisible.value = document.visibilityState === 'visible'
  if (generating.value) schedulePoll()
}

function applyState(next: LessonVideoState): void {
  clearPoll()
  videoState.value = next
  stateError.value = ''
  if (next.chapters?.length) chapters.value = [...next.chapters]
  if (next.url) videoUrl.value = mediaUrl(next.url)
  if (next.status === 'DONE' && !next.url) stateError.value = '视频已生成但地址缺失，请重新生成'
  if (next.status === 'PENDING' || next.status === 'RUNNING') schedulePoll()
}

async function refreshState(): Promise<void> {
  const wasGenerating = generating.value
  try {
    const response = await api.get<ApiEnvelope<LessonVideoState>>(videoPath.value + '/state', {
      params: { task_key: props.task.key },
      signal: requests.signal,
    })
    if (requests.signal.aborted) return
    applyState(response.data.data)
  } catch (reason) {
    if (requests.signal.aborted) return
    clearPoll()
    stateError.value = errorMessage(reason)
    if (wasGenerating) schedulePoll()
  } finally {
    stateLoading.value = false
  }
}

async function startGeneration(force: boolean): Promise<void> {
  clearPoll()
  stateError.value = ''
  try {
    const response = await api.post<ApiEnvelope<LessonVideoState>>(
      videoPath.value,
      { task_key: props.task.key, force },
      { timeout: MODEL_REQUEST_TIMEOUT_MS, signal: requests.signal },
    )
    if (requests.signal.aborted) return
    applyState(response.data.data)
  } catch (reason) {
    if (requests.signal.aborted) return
    clearPoll()
    stateError.value = errorMessage(reason)
  } finally {
    stateLoading.value = false
  }
}

async function loadLessonVideo(kick: boolean): Promise<void> {
  stateLoading.value = true
  videoState.value = null
  await refreshState()
  // 计划还没建渲染任务时补一次触发，之后只靠轮询
  if (kick && !requests.signal.aborted && videoStatus.value === 'PENDING' && jobProgress.value === 0 && !videoUrl.value) {
    await startGeneration(false)
  }
}

async function loadLesson(force = false): Promise<void> {
  lessonGenerating.value = true
  lessonError.value = ''
  try {
    const response = await api.post<ApiEnvelope<LessonResponse>>(
      '/training-plans/' + props.plan.id + '/lesson',
      { task_key: props.task.key, force },
      { timeout: MODEL_REQUEST_TIMEOUT_MS, signal: requests.signal },
    )
    generated.value = response.data.data
    videoEl.value?.pause()
    videoUrl.value = ''
    chapters.value = []
    watched.value = 0
    duration.value = 0
    activeChapter.value = 0
    if (force) await loadLessonVideo(true)
  } catch (reason) {
    lessonError.value = errorMessage(reason)
  } finally {
    lessonGenerating.value = false
  }
}

function seekChapter(index: number): void {
  const chapter = chapters.value[index]
  if (!chapter || !videoEl.value) return
  videoEl.value.currentTime = chapter.start
  activeChapter.value = index
  void videoEl.value.play().catch(() => undefined)
}

function onLoadedMetadata(): void {
  duration.value = videoEl.value?.duration ?? 0
  if (videoEl.value && videoEl.value.currentTime === 0) {
    videoEl.value.currentTime = 0.35
  }
}

function onTimeUpdate(): void {
  if (!videoEl.value) return
  const time = videoEl.value.currentTime
  watched.value = Math.max(watched.value, time)
  const index = chapters.value.findIndex((chapter, position) => {
    const next = chapters.value[position + 1]
    return time >= chapter.start && (!next || time < next.start)
  })
  if (index >= 0) activeChapter.value = index
}

onMounted(() => {
  pageVisible.value = document.visibilityState === 'visible'
  document.addEventListener('visibilitychange', onVisibilityChange)
  void loadLesson(false)
  void loadLessonVideo(true)
})
onBeforeUnmount(() => {
  requests.abort()
  clearPoll()
  document.removeEventListener('visibilitychange', onVisibilityChange)
  lectureSource?.disconnect()
  lectureAnalyser?.disconnect()
  void lectureAudio?.close()
})
</script>

<template>
  <section class="course" aria-label="沟通微课">
    <header class="course-head">
      <div>
        <p class="eyebrow">能力微课 · {{ plan.focusDimension }}</p>
        <h1>{{ courseTitle }}</h1>
      </div>
      <div class="course-tools">
        <span class="tag" v-if="props.task.completed">已完成 · 可回看</span>
        <button v-if="plan.status === 'ACTIVE' && !props.task.completedSteps.length && !props.task.completed" class="ghost" type="button" :disabled="lessonGenerating || generating" @click="loadLesson(true)">
          <RefreshCw :size="13" :stroke-width="1.8" aria-hidden="true" />
          换一门
        </button>
      </div>
    </header>

    <div class="stage">
      <video
        v-if="videoUrl"
        ref="videoEl"
        :src="videoUrl"
        controls
        crossorigin="anonymous"
        preload="metadata"
        @loadedmetadata="onLoadedMetadata"
        @timeupdate="onTimeUpdate"
        @play="onPlay"
        @pause="onPause"
        @seeking="onSeeking"
        @seeked="onSeeked"
      />

      <div v-else-if="generating" class="stage-state">
        <p class="stage-title">正在生成这节课</p>
        <div class="track" role="progressbar" :aria-valuenow="jobProgress" aria-valuemin="0" aria-valuemax="100" aria-label="微课视频生成进度">
          <i :style="{ width: jobProgress + '%' }" />
        </div>
        <p class="stage-note">{{ stageText }} · {{ jobProgress }}%</p>
      </div>

      <div v-else-if="failureText" class="stage-state">
        <p class="stage-title">这节课没有生成成功</p>
        <p class="stage-note" role="alert">{{ failureText }}</p>
        <button class="button" type="button" @click="startGeneration(true)">重新生成</button>
      </div>

      <div v-else-if="stateLoading" class="stage-state">
        <p class="stage-note">正在读取视频生成进度…</p>
      </div>

      <div v-else-if="stateError" class="stage-state">
        <p class="stage-note" role="alert">{{ stateError }}</p>
        <button class="button secondary" type="button" @click="refreshState">重新读取</button>
      </div>

      <div v-else class="stage-state">
        <p class="stage-note">这门课的视频还没有开始生成</p>
        <button class="button" type="button" @click="startGeneration(false)">生成视频</button>
      </div>

      <div v-if="TEACHER_ENABLED" class="teacher-overlay" v-show="teacherVisible">
        <CartoonPresenter ref="teacher" :active="teacherMode" :speaking="teacherSpeaking" :listening="teacherListening" label="微课老师" @configured="onTeacherConfigured" />
      </div>

      <button v-if="TEACHER_ENABLED" class="teacher-toggle" type="button" :disabled="!teacherConfigured" :aria-pressed="!teacherVisible" @click="toggleTeacher">
        {{ teacherConfigured ? (teacherVisible ? '隐藏人物' : '显示人物') : '人物准备中' }}
      </button>
    </div>

    <p v-if="failureText && videoUrl" class="error" role="alert">视频重新生成失败：{{ failureText }}</p>
    <p v-if="teacherError" class="hint" role="status">{{ teacherError }}</p>
    <p v-if="lessonError" class="hint">课程内容加载失败：{{ lessonError }}</p>

    <nav v-if="chapters.length" class="chapters" aria-label="课程章节">
      <button
        v-for="(chapter, index) in chapters"
        :key="chapter.start"
        type="button"
        :class="{ active: index === activeChapter }"
        @click="seekChapter(index)"
      >
        <span class="no">{{ String(index + 1).padStart(2, '0') }}</span>
        {{ chapter.title }}
      </button>
    </nav>

    <section v-if="lesson" class="reading" aria-label="课程文字版">
      <p v-if="lesson.intro" class="course-intro">{{ lesson.intro }}</p>
      <ol v-if="lesson.steps.length" class="reading-steps">
        <li v-for="(step, index) in lesson.steps" :key="step.title">
          <span class="no">{{ String(index + 1).padStart(2, '0') }}</span>
          <div>
            <strong>{{ step.title }}</strong>
            <p>{{ step.explanation }}</p>
            <p v-if="step.example" class="example">例：{{ step.example }}</p>
            <button class="button secondary" type="button" :disabled="submitting || task.completedSteps.includes(index) || index > task.completedSteps.length" @click="emit('completeStep', index)">{{ task.completedSteps.includes(index) ? '已学习' : '读懂了，学习下一节' }}</button>
          </div>
        </li>
      </ol>
      <p v-if="lesson.exercise" class="exercise">练习：{{ lesson.exercise }}</p>
      <p v-if="props.task.practiceFeedback" class="feedback">上次练习反馈：{{ props.task.practiceFeedback }}</p>
    </section>

    <form v-if="lesson && !task.completed" class="reading" @submit.prevent="emit('submitPractice', practice)">
      <label>用 30–60 秒重新回答一题（至少 40 字）<textarea v-model="practice" class="field" rows="4" maxlength="2000" required minlength="40" :placeholder="lesson.exercise" @focus="onPracticeFocus" @blur="onPracticeBlur" /></label>
      <p>已学 {{ task.completedSteps.length }}/{{ lesson.steps.length }} 节 · {{ task.learned ? '学习完成，等待练习通过' : '可先读文字，再提交练习' }}</p>
      <button class="button" :disabled="submitting || task.completedSteps.length < lesson.steps.length || practice.trim().length < 40">提交练习，验证是否掌握</button>
    </form>
    <footer class="course-foot">
      <div class="progress">
        <span>观看 {{ watchedPercent }}%<template v-if="duration"> · 共 {{ Math.round(duration / 60) }} 分钟</template></span>
        <div class="bar" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100">
          <i :style="{ width: (props.task.completed ? 100 : progress) + '%' }" />
        </div>
      </div>
      <button v-if="!props.task.completed" class="button" type="button" :disabled="!canFinish || submitting" @click="emit('completeCourse')">
        {{ submitting ? '提交中…' : '确认完成学习' }}
      </button>
      <RouterLink v-else class="button secondary" :to="'/plans/' + plan.id">返回计划看下一项 →</RouterLink>
    </footer>
  </section>
</template>

<style scoped>
.course { display: grid; gap: 18px; padding: clamp(20px, 3vw, 34px); border: 1px solid var(--border); border-radius: 16px; background: var(--card); }
.course-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.course-head h1 { margin: 10px 0 6px; font: 700 clamp(24px, 3vw, 34px)/1.25 var(--font-display); }
.course-intro { margin: 0; max-width: 720px; color: var(--text-2); font-size: 13.5px; line-height: 1.8; }
.course-tools { display: flex; align-items: center; gap: 10px; }
.tag { padding: 3px 10px; border: 1px solid var(--success); border-radius: 999px; color: var(--success); font-size: 11px; }
.ghost { display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; border: 1px solid var(--border); border-radius: 999px; background: transparent; color: var(--text-2); font-size: 12px; cursor: pointer; }

.stage { position: relative; border-radius: 14px; overflow: hidden; background: #0b0b0e; }
.stage video { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: contain; background: #0b0b0e; }
.stage-state { display: grid; justify-items: center; align-content: center; gap: 14px; min-height: 420px; padding: 72px 24px; color: rgba(255, 255, 255, .88); text-align: center; }
.stage-title { margin: 0; font-size: 15px; font-weight: 500; letter-spacing: .01em; }
.stage-note { margin: 0; max-width: 60ch; color: rgba(255, 255, 255, .6); font-size: 12.5px; line-height: 1.7; font-variant-numeric: tabular-nums; }
.track { width: min(420px, 72%); height: 6px; border-radius: 999px; background: rgba(255, 255, 255, .16); overflow: hidden; }
.track i { display: block; height: 100%; border-radius: 999px; background: var(--accent); transition: width .4s var(--ease); }

.teacher-overlay { position: absolute; right: 14px; bottom: 56px; width: 24%; min-width: 130px; max-width: 240px; aspect-ratio: 3 / 4; border-radius: 12px; overflow: hidden; box-shadow: 0 20px 44px rgba(6, 6, 10, .46); mask-image: linear-gradient(180deg, #000 86%, rgba(0, 0, 0, .12) 100%); -webkit-mask-image: linear-gradient(180deg, #000 86%, rgba(0, 0, 0, .12) 100%); }
.teacher-overlay :deep(.avatar-status) { top: 8px; left: 8px; padding: 3px 7px; font-size: 10px; }
.teacher-overlay :deep(.avatar-error) { inset: auto 6px 20px; gap: 6px; padding: 8px; font-size: 10px; }
.teacher-overlay :deep(.avatar-error button) { padding: 3px 7px; font-size: 10px; }
.teacher-toggle { position: absolute; top: 10px; right: 10px; z-index: 2; padding: 6px 12px; border: 1px solid rgba(255, 255, 255, .24); border-radius: 999px; background: rgba(12, 13, 18, .62); color: #fff; font-size: 11.5px; cursor: pointer; backdrop-filter: blur(6px); }
.teacher-toggle:disabled { cursor: default; opacity: .68; }

.chapters { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; }
.chapters button { display: inline-flex; align-items: center; gap: 8px; flex: none; padding: 8px 14px; border: 1px solid var(--border); border-radius: 999px; background: var(--card); color: var(--text-2); font-size: 12px; cursor: pointer; }
.chapters button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-strong); }
.chapters .no { color: var(--text-3); font-size: 10.5px; font-variant-numeric: tabular-nums; }
.reading { display: grid; gap: 12px; padding-top: 14px; border-top: 1px solid var(--divider); }
.reading-steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px; }
.reading-steps li { display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 10px; }
.reading-steps .no { padding-top: 2px; color: var(--text-3); font-size: 11px; font-variant-numeric: tabular-nums; }
.reading-steps strong { display: block; color: var(--text); font-size: 13.5px; font-weight: 600; }
.reading-steps p { margin: 4px 0 0; color: var(--text-2); font-size: 13px; line-height: 1.8; }
.reading-steps .example { color: var(--text-3); }
.exercise, .feedback { margin: 0; color: var(--text-2); font-size: 13px; line-height: 1.8; }
.feedback { color: var(--text-3); }
.course-foot { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 14px; border-top: 1px solid var(--divider); }
.progress { display: grid; gap: 6px; min-width: 220px; color: var(--text-3); font-size: 12px; }
.bar { height: 5px; border-radius: 99px; background: var(--track); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--accent); transition: width .2s var(--ease); }
.error { margin: 0; color: var(--danger); font-size: 12.5px; }
.hint { margin: 0; color: var(--text-3); font-size: 12px; }
</style>
