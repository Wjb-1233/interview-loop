import { expect, test, type Page } from '@playwright/test'

const answer = '我负责接口设计，先分析业务约束，再通过并发测试验证边界，并明确尚未验证的风险。'

async function register(page: Page) {
  const response = await page.request.post('/api/v1/auth/register', { data: {
    email: `functional-${Date.now()}@example.com`, password: 'FunctionalRepair123!', displayName: '功能回归', consent: true,
  } })
  expect(response.status()).toBe(201)
  return { Authorization: `Bearer ${(await response.json()).data.accessToken}` }
}

test('回答后立即同步必问题进度并锁定岗位，直接退出仍丢弃记录', async ({ page }) => {
  const headers = await register(page)
  const response = await page.request.post('/api/v1/training-sessions', { headers,
    data: { sceneId: 'scene-interview-03', evidenceDriven: true } })
  expect(response.status()).toBe(201)
  const session = (await response.json()).data
  await page.goto(`/training/${session.id}`)
  await page.locator('.setup > summary').click()
  await expect(page.getByText('粘贴目标岗位 JD（选填）· 面试官会按岗位考察点出题')).toBeVisible()
  const sent = page.waitForResponse(r => r.url().endsWith(`/${session.id}/messages/complete`))
  await page.getByLabel('输入面试回答').fill(answer)
  await page.getByRole('button', { name: '发送回答', exact: true }).click()
  const turn = (await (await sent).json()).data
  expect(turn.questionCovered).toBe(1)
  await expect(page.locator('.coverage-bar')).toContainText(`1 / ${turn.questionTotal}`)
  await expect(page.locator('.jd-bar textarea')).toHaveCount(0)
  await expect(page.locator('.setup')).toContainText('已开始作答，岗位和题目已固定')
  await page.locator('.plan-card summary').click()
  await expect(page.locator('.plan-list li.done')).toHaveCount(1)
  await expect(page.locator('.plan-list li').first()).toHaveClass(/done/)
  await page.getByRole('link', { name: '直接退出（不保留记录）', exact: true }).click()
  await expect(page).toHaveURL(/\/scenes$/)
  expect((await page.request.get(`/api/v1/training-sessions/${session.id}`, { headers })).status()).toBe(404)
})

for (const channel of ['VOICE', 'VIDEO']) {
  test(`${channel} 真实保存后可以修正转写并查看重评前后版本`, async ({ page }) => {
    const headers = await register(page)
    const response = await page.request.post('/api/v1/voice/sessions', { headers, multipart: {
      sceneId: 'scene-interview-03', channelHint: channel,
      turns: JSON.stringify([{ question: '请说明事务失败如何处理。', answer, startMs: 0, endMs: 4000 },
        { question: '你如何验证并发边界？', answer, startMs: 5000, endMs: 9000 }]),
    } })
    expect(response.status()).toBe(201)
    const sid = (await response.json()).data.id
    expect((await page.request.post(`/api/v1/training-sessions/${sid}/finish?create_plan=false`, { headers })).status()).toBe(200)
    await page.goto(`/report/${sid}`)
    const transcript = page.locator('.transcript')
    await expect(transcript.locator('li')).toHaveCount(2)
    await transcript.getByRole('button', { name: '修正', exact: true }).first().click()
    const corrected = '我负责接口设计，先分析业务约束，再通过并发测试验证隔离边界；还没有验证的风险会明确说明。'
    await transcript.locator('textarea').fill(corrected)
    await transcript.getByRole('button', { name: '保存修正', exact: true }).click()
    await expect(transcript.locator('.tr-text').first()).toContainText(corrected)
    await expect(page.locator('.replay-item').first()).toContainText(corrected)
    await expect(page.locator('.quality-notice')).toContainText('转写已修改')
    await transcript.getByRole('button', { name: '用新文本重新评分', exact: true }).click()
    await expect(page.locator('.revisions')).toContainText('当前第 2 版')
    const result = (await (await page.request.get(`/api/v1/evaluations/${sid}`, { headers })).json()).data
    expect(result.qualityStatus).toBe('VERIFIED')
    expect(result.revisionHistory[0].evidence[0].quote).toContain(answer)
  })
}
