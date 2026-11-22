import { expect, test, type Page } from '@playwright/test'
import type { DashboardData } from '../src/lib/dashboard'

function payload(channel = 'VOICE', samples = 3): DashboardData {
  const dimensions = { logic: 3, correctness: 4, relevance: 2, concision: 3 }
  const reference = { anchorSessionId: `latest-${channel}`, sceneId: 'scene-a', sceneTitle: '后端项目面试', channel, depth: 'STANDARD', mode: 'STANDARD', hasResume: true, hasJd: true, trainedAt: '2026-11-12T10:00:00Z' }
  return {
    summary: { sampleCount: samples, text: samples ? `近 ${samples} 次同条件正式评分，相对更稳的是信息完整，优先练习贴合问题。${samples < 3 ? '暂不判断趋势。' : ''}` : '当前比较范围内暂无正式评分。', nextAction: '下一次先直接回答题目最关心的点，再补一条相关事实。', reportSummary: samples ? `${channel}训练复盘：先回应问题，再补真实依据。` : null },
    overview: { trainingCount: 15, recentTrainingCount: 7, recentDays: 30, channelCounts: { TEXT: 8, VOICE: 5, VIDEO: 2 } },
    condition: samples ? reference : null, filterOptions: { scenes: [{ id: 'scene-a', title: '后端项目面试' }], anchors: samples ? [reference] : [] },
    formalEvaluationCount: samples, sampleCount: samples, recentSampleCount: samples, minimumTrendSamples: 3, trendReady: samples >= 3,
    latestScore: samples ? 70 : null, latestSessionId: samples ? `latest-${channel}` : null, latestTrainingAt: reference.trainedAt, recentAverage: samples ? 65 : null,
    dimensions: samples ? dimensions : null, averageDimensions: samples ? dimensions : null, styleTags: [], weaknesses: samples ? [{ dimension: '贴合问题', averageScore: 2, sampleCount: samples }] : [],
    trends: Array.from({ length: samples }, (_, i) => ({ sessionId: `sample-${i}`, date: `2026-11-12T0${i + 1}:00:00Z`, score: 60 + i * 5, dimensions })),
    delivery: channel === 'TEXT' || !samples ? null : { sessionId: `latest-${channel}`, channel, speech: { speechRate: 180, pauseCount: 0, longestPause: 0 }, camera: channel === 'VIDEO' ? { faceRatio: 0.9 } : {} },
  }
}

async function mockDashboard(page: Page, resolve: (url: URL) => DashboardData | Promise<DashboardData> = () => payload()) {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    let data: unknown = []
    if (url.pathname.endsWith('/auth/refresh')) data = { accessToken: 'dashboard-test', user: { id: 'test', email: 'test@example.com', displayName: '成长验收', role: 'STUDENT', emailVerified: true, bio: null, avatar: null } }
    else if (url.pathname.endsWith('/dashboard')) data = await resolve(url)
    else if (url.pathname.endsWith('/mistakes')) data = { items: [], total: 0 }
    await route.fulfill({ json: { data, meta: {} } }).catch(() => undefined)
  })
  return errors
}

test('自动匹配、全局概览和均分正常，不展示已移除的卡片', async ({ page }) => {
  const extraRequests: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/training-plans' || path === '/api/v1/training-sessions/mistakes') extraRequests.push(path)
  })
  const errors = await mockDashboard(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '训练概览', exact: true })).toBeVisible()
  await expect(page.getByText('最近一次成绩', { exact: true })).toBeVisible()
  await expect(page.getByText('近 3 次同条件均分', { exact: true })).toBeVisible()
  await expect(page.locator('.today-card, .retests')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '复测与原话证据', exact: true })).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: '比较训练方式', exact: true })).toBeHidden()
  await expect(page.getByRole('img', { name: '同条件正式评分趋势', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '最近一次的语音与镜头表现', exact: true })).toBeVisible()
  await page.getByText('调整比较范围', { exact: true }).click()
  const selected = page.waitForRequest((request) => request.url().includes('anchor_session_id=latest-VOICE'))
  await page.getByRole('combobox', { name: '参考训练', exact: true }).selectOption('latest-VOICE')
  await selected
  expect(extraRequests).toEqual([])
  expect(errors).toEqual([])
})

test('筛选后概览保持全局口径，样本不足和无正式评分有明确状态', async ({ page }) => {
  await mockDashboard(page, (url) => payload(url.searchParams.get('channel') || 'VOICE', url.searchParams.get('channel') === 'VIDEO' ? 0 : url.searchParams.get('channel') ? 1 : 3))
  await page.goto('/')
  const overview = page.getByRole('region', { name: '训练概览', exact: true })
  await expect(overview).toContainText('15')
  await page.getByText('调整比较范围', { exact: true }).click()
  await page.getByRole('combobox', { name: '比较训练方式', exact: true }).selectOption('TEXT')
  await expect(page.getByText('记录不足，暂不判断成长。', { exact: false })).toBeVisible()
  await expect(page.getByRole('img', { name: '同条件正式评分趋势', exact: true })).toHaveCount(0)
  await expect(overview).toContainText('15')
  await page.getByRole('combobox', { name: '比较训练方式', exact: true }).selectOption('VIDEO')
  await expect(page.getByText('这个范围内暂无正式评分', { exact: true })).toBeVisible()
  await expect(page.getByText('最近一次成绩', { exact: true })).toHaveCount(0)
  await expect(overview).toContainText('15')
  await page.getByRole('button', { name: '恢复自动匹配', exact: true }).click()
  await expect(page.getByRole('img', { name: '同条件正式评分趋势', exact: true })).toBeVisible()
})

test('快速切换筛选时较慢的旧请求不能覆盖新结果', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  let oldFinished!: () => void
  const finished = new Promise<void>((resolve) => { oldFinished = resolve })
  await mockDashboard(page, async (url) => {
    const channel = url.searchParams.get('channel') || 'TEXT'
    if (channel === 'VOICE') { await gate; oldFinished() }
    const data = payload(channel)
    data.latestScore = channel === 'VIDEO' ? 88 : 30
    return data
  })
  await page.goto('/')
  await page.getByText('调整比较范围', { exact: true }).click()
  const requested = page.waitForRequest((request) => request.url().includes('/dashboard?channel=VOICE'))
  await page.getByRole('combobox', { name: '比较训练方式', exact: true }).selectOption('VOICE')
  await requested
  await page.getByRole('combobox', { name: '比较训练方式', exact: true }).selectOption('VIDEO')
  await expect(page.locator('.hero .figure')).toContainText('88')
  release()
  await finished
  await expect(page.locator('.hero .figure')).toContainText('88')
  await expect(page.locator('.scope')).toContainText('视频')
})

test('桌面看板布局正常且没有计划或复测卡片', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  const errors = await mockDashboard(page, () => {
    const data = payload('VIDEO')
    return data
  })
  await page.goto('/')
  await expect(page.getByText('最近一次成绩', { exact: true })).toBeVisible()
  await expect(page.locator('.today-card, .retests')).toHaveCount(0)
  await page.getByText('调整比较范围', { exact: true }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: '../docs/evidence/dashboard-growth-review.png', fullPage: true })
  expect(errors).toEqual([])
})

test('首次训练前展示成长起点，不显示零分能力', async ({ page }) => {
  await mockDashboard(page, () => {
    const data = payload('TEXT', 0)
    data.overview = { trainingCount: 0, recentTrainingCount: 0, recentDays: 30, channelCounts: { TEXT: 0, VOICE: 0, VIDEO: 0 } }
    return data
  })
  await page.goto('/')
  await expect(page.getByText('先完成一场对练，建立你的成长起点', { exact: true })).toBeVisible()
  await expect(page.locator('.hero')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '去选场景', exact: false })).toBeVisible()
})

test('加载失败保留明确错误，重试后恢复看板而不是显示零分', async ({ page }) => {
  await mockDashboard(page)
  let attempts = 0
  await page.route('**/api/v1/dashboard**', async (route) => {
    if (attempts++ === 0) return route.fulfill({ status: 503, json: { detail: '训练数据暂时不可用，请重试。' } })
    return route.fallback()
  })
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('训练数据暂时不可用')
  await expect(page.locator('.hero')).toHaveCount(0)
  await page.getByRole('button', { name: '重新加载', exact: true }).click()
  await expect(page.getByText('最近一次成绩', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('最近一次的小数成绩按原值显示', async ({ page }) => {
  await mockDashboard(page, () => ({ ...payload(), latestScore: 70.5 }))
  await page.goto('/')
  await expect(page.locator('.hero .figure .num')).toHaveText('70.5')
})

test('训练总结包含复盘和具体练习动作，并跟随筛选切换', async ({ page }) => {
  await mockDashboard(page, (url) => payload(url.searchParams.get('channel') || 'VOICE', url.searchParams.get('channel') ? 1 : 3))
  await page.goto('/')
  const summary = page.getByRole('region', { name: '训练总结', exact: true })
  await expect(summary).toContainText('VOICE训练复盘')
  await expect(summary).toContainText('下一次怎么练')
  await expect(summary).toContainText('直接回答题目最关心的点')
  await page.getByText('调整比较范围', { exact: true }).click()
  await page.getByRole('combobox', { name: '比较训练方式', exact: true }).selectOption('TEXT')
  await expect(summary).toContainText('TEXT训练复盘')
  await expect(summary).toContainText('暂不判断趋势')
  await expect(summary).not.toContainText('VOICE训练复盘')
})
