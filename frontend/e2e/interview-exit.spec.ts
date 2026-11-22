import { expect, test, type Page } from '@playwright/test'

async function textAttempt(page: Page, rounds = 1, failDiscard = false, showScene = false) {
  const discarded: string[] = []
  let finished = 0
  let rejectExit = failDiscard
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const training = { id: 'exit-demo', sceneId: 'scene-demo', sceneTitle: '退出行为测试', status: 'ACTIVE', currentRound: rounds, maxRounds: 8, channel: 'TEXT', stage: 'DISCOVERY', startedAt: '2026-11-16T03:00:00Z', messages: [{ id: 'q', roundNo: 0, speaker: 'AI', content: '请介绍项目。', flags: [] }, ...Array.from({ length: rounds }, (_, i) => ({ id: `a-${i}`, roundNo: i + 1, speaker: 'USER', content: '我负责接口，通过监控验证结果。', flags: [] }))] }
  const evaluation = { id: 'report', sessionId: training.id, scores: { logic: 3, relevance: 3, correctness: 3, concision: 3 }, overallScore: 60, summary: '本次总结只根据已经提交的回答。', suggestions: [], styleTags: [], evidence: [], degraded: false, qualityStatus: 'LIMITED_SAMPLE', answeredRounds: rounds, eligibleForGrowth: false, createdAt: training.startedAt, previousScores: null, previousOverall: null, planId: null }
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path.endsWith('/auth/refresh')) data = { accessToken: 'exit-token', user: { id: 'test', displayName: '退出验收', role: 'STUDENT' } }
    else if (path.endsWith('/scenes') && showScene) data = [{ id: 'scene-demo', title: '退出行为测试', category: '技术面', industry: '互联网', position: '后端开发', roleName: '面试官', difficulty: '入门', background: '介绍项目经历', goal: '解释验证过程', tags: [], openingLine: '请介绍项目', favorite: false }]
    else if (path.endsWith('/training-sessions/prepare')) data = training
    else if (path.endsWith('/training-sessions/exit-demo/discard')) {
      discarded.push(route.request().headers().authorization ?? '')
      if (rejectExit) { rejectExit = false; await route.fulfill({ status: 503, json: { detail: '清理暂时不可用' } }); return }
      await route.fulfill({ status: 204 }); return
    } else if (path.endsWith('/finish')) { finished++; training.status = 'FINISHED'; data = evaluation }
    else if (path.endsWith('/evaluations/exit-demo')) data = evaluation
    else if (path.endsWith('/training-sessions/exit-demo')) data = training
    else if (path.endsWith('/mistakes')) data = { items: [], total: 0 }
    await route.fulfill({ json: { data, meta: {} } })
  })
  return { discarded, finished: () => finished, errors }
}

for (const rounds of [0, 1, 3]) {
  test(`文字面试已答 ${rounds} 轮，直接退出只丢弃且不生成报告`, async ({ page }) => {
    const state = await textAttempt(page, rounds)
    await page.addInitScript(() => {
      localStorage.setItem('yanjie:draft:exit-demo:4', '未提交的本场草稿')
      localStorage.setItem('yanjie:draft:another-session:1', '其他场次草稿')
    })
    await page.goto('/training/exit-demo')
    await expect(page.getByRole('button', { name: '结束面试', exact: true })).toHaveCount(1)
    await page.getByRole('link', { name: '直接退出（不保留记录）', exact: true }).click()
    await expect(page).toHaveURL(/\/scenes$/)
    expect(state.discarded).toEqual(['Bearer exit-token'])
    expect(state.finished()).toBe(0)
    expect(await page.evaluate(() => localStorage.getItem('yanjie:draft:exit-demo:4'))).toBeNull()
    expect(await page.evaluate(() => localStorage.getItem('yanjie:draft:another-session:1'))).toBe('其他场次草稿')
    expect(state.errors).toEqual([])
  })
}

test('点击结束面试立即按一轮作答生成总结，跳转报告不会丢弃', async ({ page }) => {
  const state = await textAttempt(page)
  await page.goto('/training/exit-demo')
  await page.getByRole('button', { name: '结束面试', exact: true }).click()
  await expect(page).toHaveURL(/\/report\/exit-demo$/)
  await expect(page.locator('.summary-text')).toHaveText('本次总结只根据已经提交的回答。')
  await expect(page.locator('.quality-notice')).toContainText('本次已作答 1 轮')
  expect(state.finished()).toBe(1)
  expect(state.discarded).toHaveLength(0)
  expect(state.errors).toEqual([])
})

test('浏览器后退离开本场，同样丢弃未结束的回答', async ({ page }) => {
  const state = await textAttempt(page, 1, false, true)
  await page.goto('/scenes')
  await page.locator('.scene-card').getByRole('button', { name: '文字', exact: true }).click()
  await page.getByRole('button', { name: '直接开始', exact: true }).click()
  await expect(page).toHaveURL(/\/training\/exit-demo(?:\?|$)/)
  await expect(page.getByRole('button', { name: '结束面试', exact: true })).toBeEnabled()
  await page.goBack()
  await expect(page).toHaveURL(/\/scenes$/)
  await expect.poll(() => state.discarded.length).toBeGreaterThan(0)
  expect(state.finished()).toBe(0)
})

test('零作答禁用结束；点击侧栏离开也会清理', async ({ page }) => {
  const state = await textAttempt(page, 0)
  await page.goto('/training/exit-demo')
  await expect(page.getByRole('button', { name: '结束面试', exact: true })).toBeDisabled()
  await page.getByRole('link', { name: '训练记录', exact: true }).click()
  await expect(page).toHaveURL(/\/history$/)
  expect(state.discarded).toHaveLength(1)
  expect(state.finished()).toBe(0)
})

test('页面关闭事件发送携带认证的清理请求', async ({ page }) => {
  const state = await textAttempt(page)
  await page.goto('/training/exit-demo')
  await expect(page.getByRole('button', { name: '结束面试', exact: true })).toBeEnabled()
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')))
  await expect.poll(() => state.discarded).toEqual(['Bearer exit-token'])
  expect(state.finished()).toBe(0)
})

test('清理失败留在当前页提示重试，不把失败显示为退出成功', async ({ page }) => {
  const state = await textAttempt(page, 1, true)
  await page.goto('/training/exit-demo')
  await page.getByRole('link', { name: '直接退出（不保留记录）', exact: true }).click()
  await expect(page.locator('.error-banner')).toContainText('退出清理未完成')
  await expect(page).toHaveURL(/\/training\/exit-demo$/)
  await page.getByRole('link', { name: '直接退出（不保留记录）', exact: true }).click()
  await expect(page).toHaveURL(/\/scenes$/)
  expect(state.discarded).toHaveLength(2)
})

test('退出登录先清理本场，再清除认证，登录页不会被清理守卫挡住', async ({ page }) => {
  const state = await textAttempt(page)
  await page.goto('/training/exit-demo')
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  expect(state.discarded).toEqual(['Bearer exit-token'])
  expect(state.finished()).toBe(0)
  expect(state.errors).toEqual([])
})

test('原有 mode=voice 链接仍显示语音输入，退出只丢弃本场', async ({ page }) => {
  const state = await textAttempt(page)
  await page.goto('/training/exit-demo?mode=voice')
  await expect(page.getByRole('region', { name: '语音面试控制台' })).toBeVisible()
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  expect(state.discarded).toEqual(['Bearer exit-token'])
  expect(state.finished()).toBe(0)
  expect(state.errors).toEqual([])
})
