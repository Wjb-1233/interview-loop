import { expect, test } from '@playwright/test'

test('报告自评仍可读取保存，已移除的分享不再显示或请求', async ({ page }) => {
  const errors: string[] = []
  const reviews: unknown[] = []
  const shareRequests: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const createdAt = '2026-11-17T01:00:00Z'
  const scores = { logic: 3, relevance: 3, correctness: 3, concision: 3 }
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path.endsWith('/auth/refresh')) data = { accessToken: 'report-test', user: { id: 'test', role: 'STUDENT', displayName: '报告验收' } }
    else if (path.endsWith('/evaluations/refactor-report')) data = { id: 'eval', sessionId: 'refactor-report', scores, overallScore: 60, summary: '原报告总评', suggestions: [], styleTags: [], evidence: [], degraded: false, createdAt }
    else if (path === '/api/v1/training-sessions/refactor-report') data = { id: 'refactor-report', sceneId: 'scene', sceneTitle: '自评验收', channel: 'VIDEO', status: 'FINISHED', currentRound: 1, startedAt: createdAt, messages: [{ id: 'q', roundNo: 1, speaker: 'AI', content: '介绍你的项目', flags: [] }, { id: 'a', roundNo: 1, speaker: 'USER', content: '我负责接口设计', flags: [] }], delivery: { selfReview: [{ roundNo: 1, camera: true, structure: false, opening: false, note: '原自评' }] } }
    else if (path.endsWith('/self-review')) { reviews.push(route.request().postDataJSON()); data = {} }
    else if (path.includes('/share/')) shareRequests.push(path)
    await route.fulfill({ json: { data, meta: {} } })
  })
  await page.goto('/report/refactor-report')
  const review = page.locator('.self-review')
  await expect(review.locator('input[type=checkbox]').first()).toBeChecked()
  await expect(review.locator('.note')).toHaveValue('原自评')
  await review.locator('.note').fill('修改后的自评')
  await review.getByRole('button', { name: '保存自评', exact: true }).click()
  await expect(review.getByRole('button')).toContainText('已保存')
  expect(reviews).toEqual([{ items: [expect.objectContaining({ roundNo: 1, camera: true, note: '修改后的自评' })] }])
  await expect(page.getByRole('button', { name: /生成教练链接|撤销分享链接/ })).toHaveCount(0)
  expect(shareRequests).toEqual([])
  expect(errors).toEqual([])
})

test('报告的知识题不套用 STAR，经历题保留结构提示及同题成绩', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const questions = ['请解释事务的原子性。', '介绍一个你负责过的项目。']
  const answers = ['事务要么全部成功，要么全部回滚，例如转账，仍需注意隔离性边界。', '我负责报名接口，设计事务边界，最终通过压测验证结果。']
  const scores = { logic: 3, relevance: 4, correctness: 4, concision: 4 }
  const evaluation = { id: 'evaluation-demo', sessionId: 'review-demo', scores, overallScore: 75, summary: '思路清楚，还需补充已验证的依据。', suggestions: [], styleTags: [], evidence: [], speechStats: { fillerTotal: 1, topFillers: [{ word: '然后', count: 1 }] }, createdAt: '2026-11-14T03:00:00Z', degraded: false, questionTypes: [{ roundNo: 1, type: 'KNOWLEDGE' }, { roundNo: 2, type: 'EXPERIENCE' }] }
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path.endsWith('/auth/refresh')) data = { accessToken: 'report-test', user: { id: 'test', role: 'STUDENT', displayName: '报告验收' } }
    else if (path.endsWith('/evaluations/review-demo')) data = evaluation
    else if (path.endsWith('/training-sessions/review-demo')) data = { id: 'review-demo', sceneId: 'scene-review', sceneTitle: '后端开发技术面试', channel: 'VOICE', status: 'FINISHED', currentRound: 2, startedAt: evaluation.createdAt, finishedAt: evaluation.createdAt, questionPlan: [], messages: questions.flatMap((question, i) => [{ id: `q-${i}`, speaker: 'AI', roundNo: i + 1, content: question, flags: [] }, { id: `a-${i}`, speaker: 'USER', roundNo: i + 1, content: answers[i], flags: [] }]) }
    else if (path.includes('/same-question/')) data = { attempts: [{ sessionId: 'previous-demo', startedAt: evaluation.createdAt, isCurrent: false, question: questions[0], answer: answers[0], overallScore: 70, channel: 'VOICE' }] }
    await route.fulfill({ json: { data, meta: {} } })
  })
  await page.goto('/report/review-demo')
  const rounds = page.locator('.replay-item')
  await expect(rounds).toHaveCount(2)
  await expect(page.locator('.actions-card')).toHaveCount(0)
  await expect(rounds.nth(0)).not.toContainText('STAR')
  await expect(rounds.nth(1)).toContainText('STAR')
  await rounds.nth(0).getByRole('button', { name: '同题对比', exact: true }).click()
  await expect(rounds.nth(0)).toContainText('70 分')
  await expect(rounds.nth(0)).not.toContainText('STAR')
  expect(errors).toEqual([])
})

for (const status of ['PENDING_RESCORE', 'INSUFFICIENT_EVIDENCE'] as const) {
  test(`报告明确展示 ${status}，补评后展示历史版本`, async ({ page }) => {
    let repaired = false
    let rescoreCalls = 0
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const scores = { logic: 3, relevance: 3, correctness: 3, concision: 3 }
    const old = { revision: 1, overallScore: 60, createdAt: '2026-11-16T01:00:00Z', summary: '原评分总评', evidence: [{ dimension: 'logic', roundNo: 1, quote: '修改前的原话' }] }
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data: unknown = []
      if (path.endsWith('/auth/refresh')) data = { accessToken: 'quality-test', user: { id: 'test', role: 'STUDENT', displayName: '质量验收' } }
      else if (path.endsWith('/evaluations/quality-demo')) {
        if (route.request().method() === 'POST') {
          rescoreCalls++
          if (status === 'PENDING_RESCORE' && rescoreCalls === 1) {
            await route.fulfill({ status: 503, json: { title: 'RESCORE_UNAVAILABLE', detail: '重新评分暂时不可用，原报告已保留，请稍后重试' } })
            return
          }
          repaired = true
        }
        data = { id: 'eval', sessionId: 'quality-demo', scores, overallScore: repaired ? 80 : 60, summary: '评分总评', suggestions: [], styleTags: [], evidence: [], degraded: false, qualityStatus: repaired ? 'VERIFIED' : status, eligibleForGrowth: repaired, missingEvidenceDimensions: repaired ? [] : ['relevance', 'correctness'], revision: repaired ? 2 : 1, revisionHistory: repaired ? [old] : [], createdAt: old.createdAt }
      } else if (path.endsWith('/training-sessions/quality-demo')) data = { id: 'quality-demo', sceneId: 'scene', sceneTitle: '评分校验', channel: 'VOICE', status: 'FINISHED', currentRound: 2, messages: [], delivery: { rescoreRequired: !repaired && status === 'PENDING_RESCORE' }, startedAt: old.createdAt }
      await route.fulfill({ json: { data, meta: {} } })
    })
    await page.goto('/report/quality-demo')
    const notice = page.locator('.quality-notice')
    await expect(notice).toContainText(status === 'PENDING_RESCORE' ? '转写已修改' : '贴合问题、信息完整')
    await expect(notice).toContainText('参考')
    await notice.getByRole('button').click()
    if (status === 'PENDING_RESCORE') {
      await expect(page.locator('.error-banner')).toBeVisible()
      await expect(notice).toBeVisible()
      await expect(page.locator('.summary-text')).toHaveText('评分总评')
      await notice.getByRole('button').click()
    }
    await expect(notice).toHaveCount(0)
    const history = page.locator('.revisions')
    await expect(history).toContainText('当前第 2 版')
    await history.locator('summary').click()
    await expect(history).toContainText('原评分总评')
    await expect(history).toContainText('修改前的原话')
    expect(rescoreCalls).toBe(status === 'PENDING_RESCORE' ? 2 : 1)
    expect(errors).toEqual([])
  })
}
