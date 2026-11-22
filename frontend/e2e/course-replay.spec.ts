import { expect, test, type Page } from '@playwright/test'
import { fileURLToPath } from 'node:url'

// 3 秒纯色无声视频，由 ffmpeg 生成，不依赖真实课程或云端渲染。
const videoFixture = fileURLToPath(new URL('./fixtures/lesson-replay.mp4', import.meta.url))
const audioVideoFixture = fileURLToPath(new URL('./fixtures/avatar-speech.mp4', import.meta.url))
const lesson = {
  title: '先给结论，再补事实', intro: '把回答组织成清楚的结论、具体的事实和下一步行动。', aiGenerated: false,
  steps: ['先给结论', '补充事实', '明确行动'].map((title) => ({ title, explanation: '围绕原问题清楚表达，用真实经历说明自己的判断。', example: '我的结论是先修复问题，我负责验证后同步处理结果。' })),
  exercise: '结合最近一次项目经历，说明你的结论、依据和后续行动。',
}

async function mockCourse(page: Page, options: { cached?: boolean; completed?: boolean; cacheFails?: boolean; delay?: boolean; audio?: boolean; progress?: boolean } = {}) {
  const state = { renders: 0, cacheReads: 0, cached: options.cached ?? true, changed: false, errors: [] as string[] }
  const task = { key: 'course', day: 1, actionType: 'COURSE', task: '学习微课', lesson, completed: options.completed ?? false, completedSteps: options.completed ? [0, 1, 2] : [], learningProgress: options.completed ? 100 : 0, learned: options.completed ?? false, practicePassed: options.completed ?? false }
  const plan = { id: 'replay-plan', sequence: 1, title: '表达提升计划', focusDimension: '内容与逻辑', status: options.completed ? 'COMPLETED' : 'ACTIVE', progress: options.completed ? 100 : 0, createdAt: '2026-11-12T02:00:00Z', tasks: [task] }
  const chapters = [{ title: '先给结论', start: 0, duration: 1 }, { title: '补充事实', start: 1, duration: 2 }]
  const videoState = (override?: { status: string; progress: number }) => override
    ? { jobId: 'replay-job', status: override.status, progress: override.progress, stage: null, url: null, chapters: [], error: null }
    : state.cached
      ? { jobId: 'replay-job', status: 'DONE', progress: 100, stage: '已完成', url: '/media/lessons/replay-saved.mp4', chapters, error: null }
      : { jobId: null, status: 'PENDING', progress: 0, stage: null, url: null, chapters: [], error: null }
  page.on('pageerror', (error) => state.errors.push(error.message))
  await page.route('**/media/lessons/**', (route) => route.fulfill({ path: options.audio ? audioVideoFixture : videoFixture, contentType: 'video/mp4' }))
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path.endsWith('/auth/refresh')) data = { accessToken: 'course-test', user: { id: 'test', role: 'STUDENT', displayName: '课程回看' } }
    else if (path.endsWith('/training-plans/replay-plan')) data = plan
    else if (path.endsWith('/lesson/video/state')) {
      // 组件用 GET /training-plans/{id}/lesson/video/state 读进度，返回 LessonVideoState。
      // 计划页（/plans/...）的轮询不计入缓存读取次数，只统计课程页（/plan-lesson）的读取。
      const fromLessonPage = (route.request().frame()?.url() ?? '').includes('/plan-lesson')
      if (fromLessonPage) {
        state.cacheReads++
        if (options.delay) await new Promise((resolve) => setTimeout(resolve, 250))
        if (options.cacheFails && state.cacheReads === 1) { await route.fulfill({ status: 503, json: { detail: '暂时无法读取视频' } }); return }
      }
      data = videoState()
    } else if (path.endsWith('/lesson/video')) {
      // POST 触发渲染；GET 是旧接口，保留兜底
      if (route.request().method() === 'POST') {
        state.renders++
        state.cached = true
        // progress 模式下先返回「生成中」，下一次 GET /state 才给 DONE，用于断言进度态
        if (options.progress) { await route.fulfill({ json: { data: videoState({ status: 'RUNNING', progress: 40 }), meta: {} } }); return }
      }
      data = videoState()
    } else if (path.endsWith('/lesson')) {
      if (route.request().postDataJSON().force) { state.changed = true; state.cached = false }
      data = { lesson: state.changed ? { ...lesson, title: '换课后的新内容' } : lesson, source: { title: lesson.title, description: '', content: '' } }
    } else { await route.fulfill({ status: 404, json: { detail: '此测试未提供该接口' } }); return }
    await route.fulfill({ json: { data, meta: {} } })
  })
  return state
}

test('历史计划微课直接播放，返回和刷新后均无需重新生成', async ({ page }) => {
  const state = await mockCourse(page, { completed: true, delay: true })
  await page.goto('/plans/replay-plan')
  await page.getByRole('link', { name: '回看 →', exact: true }).click()
  await expect(page.getByText('正在读取视频生成进度…', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '生成视频', exact: true })).toHaveCount(0)
  const video = page.locator('.stage video')
  await expect(video).toHaveAttribute('src', '/media/lessons/replay-saved.mp4')
  await video.evaluate(async (element: HTMLVideoElement) => { await element.play() })
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(.4)
  await page.getByRole('button', { name: /补充事实/ }).click()
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThanOrEqual(1)
  await page.getByRole('link', { name: '← 返回训练计划', exact: true }).click()
  await page.getByRole('link', { name: '回看 →', exact: true }).click()
  await expect(video).toBeVisible()
  await page.reload()
  await expect(video).toHaveAttribute('src', '/media/lessons/replay-saved.mp4')
  expect(state.cacheReads).toBe(3)
  expect(state.renders).toBe(0)
  await expect(page.getByRole('button', { name: '换一门', exact: true })).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('首次进入课程自动触发视频生成，重新进入后自动复用', async ({ page }) => {
  const state = await mockCourse(page, { cached: false, progress: true })
  const posts: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/lesson/video')) posts.push(request.url())
  })
  await page.goto('/plan-lesson?planId=replay-plan&taskKey=course')
  // 不点任何按钮：PENDING 时组件自己补一次触发，直接进入进度态
  await expect(page.getByText('正在生成这节课', { exact: true })).toBeVisible()
  await expect(page.getByRole('progressbar', { name: '微课视频生成进度' })).toHaveAttribute('aria-valuenow', '40')
  expect(posts).toHaveLength(1)
  await expect(page.getByRole('button', { name: '生成视频', exact: true })).toHaveCount(0)
  await expect(page.locator('.stage video')).toBeVisible({ timeout: 10_000 })
  await page.reload()
  await expect(page.locator('.stage video')).toBeVisible()
  expect(state.renders).toBe(1)
  expect(state.errors).toEqual([])
})

test('视频读取失败显示重试入口，不误提示重新生成', async ({ page }) => {
  const state = await mockCourse(page, { cacheFails: true })
  await page.goto('/plan-lesson?planId=replay-plan&taskKey=course')
  await expect(page.getByRole('alert')).toContainText('暂时无法读取视频')
  await expect(page.getByRole('button', { name: '生成视频', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(page.locator('.stage video')).toBeVisible()
  expect(state.cacheReads).toBe(2)
  expect(state.renders).toBe(0)
  expect(state.errors).toEqual([])
})

test('主动换课后清除旧视频，并自动发起新视频生成', async ({ page }) => {
  const state = await mockCourse(page, { progress: true })
  await page.goto('/plan-lesson?planId=replay-plan&taskKey=course')
  await expect(page.locator('.stage video')).toBeVisible()
  await page.getByRole('button', { name: '换一门', exact: true }).click()
  await expect(page.getByRole('heading', { name: '换课后的新内容', exact: true })).toBeVisible()
  // 换课后旧视频立即清空，随后自动发起一次生成（不用点按钮）并进入进度态
  await expect(page.locator('.stage video')).toHaveCount(0)
  await expect(page.getByText('正在生成这节课', { exact: true })).toBeVisible()
  await expect(page.locator('.stage video')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '生成视频', exact: true })).toHaveCount(0)
  await expect.poll(() => state.renders).toBe(1)
  expect(state.errors).toEqual([])
})

// 微课讲师按要求长期下线（PersonalizedLesson.vue: TEACHER_ENABLED = false），
// 这里断言的是下线后的真实保证：不加载任何人物形象与人物资源，视频照常播放。
test('无人物形象的微课：不请求人物资源，视频原声播放与暂停正常', async ({ page }) => {
  const presenterRequests: string[] = []
  page.on('request', (request) => {
    const url = request.url()
    if (url.includes('/avatars/') || url.includes('/live2d')) presenterRequests.push(url)
  })
  const state = await mockCourse(page, { audio: true, completed: true })
  await page.goto('/plan-lesson?planId=replay-plan&taskKey=course')
  const video = page.locator('.stage video')
  await expect(video).toBeVisible()
  await expect(page.locator('.avatar-presenter')).toHaveCount(0)
  await expect(page.getByText('人物准备中', { exact: true })).toHaveCount(0)
  await video.evaluate(async (element: HTMLVideoElement) => { await element.play() })
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(.4)
  await video.evaluate((element: HTMLVideoElement) => element.pause())
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true)
  expect(presenterRequests).toEqual([])
  expect(state.renders).toBe(0)
  expect(state.errors).toEqual([])
})

test('微课讲师长期下线：整个回看流程都不加载人物形象', async ({ page }) => {
  const presenterRequests: string[] = []
  page.on('request', (request) => {
    const url = request.url()
    if (url.includes('/avatars/') || url.includes('/live2d')) presenterRequests.push(url)
  })
  const state = await mockCourse(page, { completed: true })
  await page.goto('/plans/replay-plan')
  await page.getByRole('link', { name: '回看 →', exact: true }).click()
  const video = page.locator('.stage video')
  await expect(video).toBeVisible()
  await video.evaluate(async (element: HTMLVideoElement) => { await element.play() })
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(.4)
  await expect(page.locator('.avatar-presenter')).toHaveCount(0)
  await expect(page.getByText('人物准备中', { exact: true })).toHaveCount(0)
  expect(presenterRequests).toEqual([])
  expect(state.renders).toBe(0)
  expect(state.errors).toEqual([])
})
