import { expect, test, type Page } from '@playwright/test'

const answer = '我负责订单接口设计，先分析热点数据，再通过缓存减少重复查询，最终使用监控对比延迟，同时检查缓存一致性和异常边界。'

async function register(page: Page) {
  const response = await page.request.post('/api/v1/auth/register', { data: { email: `upgrade-${Date.now()}@example.com`, password: 'UpgradeBrowser123!', displayName: '浏览器验收', consent: true } })
  expect(response.status()).toBe(201)
  return { Authorization: `Bearer ${(await response.json()).data.accessToken}` }
}

test('新用户独立改写并在统一话术库收藏筛选', async ({ page }) => {
  await register(page)
  await page.goto('/scripts')
  await page.getByPlaceholder('例如：这个项目我负责后端，做了很多优化。').fill(answer)
  await page.getByRole('button', { name: '生成三种风格', exact: true }).click()
  await expect(page.locator('.version-card')).toHaveCount(3)
  await page.getByRole('button', { name: '☆ 收藏', exact: true }).first().click()
  await expect(page.getByRole('button', { name: '★ 已收藏', exact: true })).toHaveCount(1)
  await page.getByRole('link', { name: '话术库', exact: true }).click()
  await page.getByRole('button', { name: '已收藏', exact: true }).click()
  await expect(page.locator('.version-card')).toHaveCount(1)
})

test('三种面试使用共同准备页且仅保留中文', async ({ page }) => {
  await register(page)
  for (const [label, channel] of [['文字', 'TEXT'], ['语音', 'VOICE'], ['视频', 'VIDEO']]) {
    await page.goto('/scenes?sceneId=scene-interview-03')
    await expect(page.getByRole('button', { name: 'English', exact: true })).toHaveCount(0)
    await page.locator('.scene-card').getByRole('button', { name: label, exact: true }).click()
    await page.getByPlaceholder('粘贴至少 20 字的岗位职责与要求').fill('后端开发岗位，需要熟悉 Python、接口设计、数据库与缓存，并能分析和验证性能问题。')
    if (channel !== 'TEXT') await page.locator('dialog select').selectOption('5')
    const prepared = page.waitForResponse((r) => r.url().endsWith('/training-sessions/prepare') && r.request().method() === 'POST')
    await page.getByRole('button', { name: '直接开始', exact: true }).click()
    const response = await prepared
    expect(response.status()).toBe(201)
    expect((await response.json()).data.channel).toBe(channel)
    await expect(page).toHaveURL(channel === 'TEXT' ? /\/training\// : channel === 'VOICE' ? /\/voice\?/ : /\/video\?/)
    await expect(page.getByRole('button', { name: '本地管线', exact: true })).toHaveCount(0)
  }
})

test('复盘改写文字微课到界面复测完成整份计划', async ({ page }) => {
  test.setTimeout(120_000)
  const headers = await register(page)
  const created = await page.request.post('/api/v1/training-sessions/prepare', { headers, multipart: { sceneId: 'scene-interview-03', depth: 'STANDARD' } })
  expect(created.status()).toBe(201)
  const sessionId = (await created.json()).data.id
  for (let i = 0; i < 6; i++) expect((await page.request.post(`/api/v1/training-sessions/${sessionId}/messages/complete`, { headers, data: { content: answer } })).status()).toBe(200)
  expect((await page.request.post(`/api/v1/training-sessions/${sessionId}/finish`, { headers })).status()).toBe(200)
  const plans = (await (await page.request.get('/api/v1/training-plans', { headers })).json()).data
  const planId = plans[0].id
  await page.goto(`/plans/${planId}`)
  await page.getByRole('button', { name: '确认已复盘', exact: true }).click()
  await page.getByLabel('你的新回答').fill(answer)
  await page.getByRole('button', { name: '提交改写并检查', exact: true }).click()
  await expect(page.getByRole('heading', { name: '重答一题', exact: true })).toHaveCount(0)
  await page.getByRole('link', { name: '开始学习 →', exact: true }).click()
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: '读懂了，学习下一节', exact: true }).first().click()
    await expect(page.getByRole('button', { name: '已学习', exact: true })).toHaveCount(i + 1)
  }
  await page.getByRole('button', { name: '确认完成学习', exact: true }).click()
  await page.getByLabel('用 30–60 秒重新回答一题（至少 40 字）').fill(answer)
  await page.getByRole('button', { name: '提交练习，验证是否掌握', exact: true }).click()
  await page.getByRole('link', { name: '返回计划看下一项 →', exact: true }).click()
  await page.getByRole('link', { name: '去做 →', exact: true }).click()
  await page.locator('.scene-card').getByRole('button', { name: '文字', exact: true }).click()
  await page.getByRole('button', { name: '直接开始', exact: true }).click()
  await expect(page).toHaveURL(/\/training\//)
  for (let i = 0; i < 6; i++) {
    await page.getByLabel('输入面试回答').fill(answer)
    await page.getByRole('button', { name: '发送回答', exact: true }).click()
    await expect(page.getByRole('button', { name: '发送回答', exact: true })).toBeVisible()
  }
  await page.getByRole('button', { name: '结束面试', exact: true }).click()
  await expect(page).toHaveURL(/\/report\//)
  await page.goto(`/plans/${planId}`)
  await expect(page.getByText('4 / 4 已完成 · 100%', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '复测前后对比', exact: true })).toBeVisible()
  await page.screenshot({ path: '../docs/evidence/upgrade-plan-complete.png', fullPage: true })
})

test('同场景重新开始会加载新会话而且回答写入新会话', async ({ page }) => {
  const headers = await register(page)
  const created = await page.request.post('/api/v1/training-sessions/prepare', { headers, multipart: { sceneId: 'scene-interview-03', depth: 'PRESSURE' } })
  const original = (await created.json()).data
  for (let i = 0; i < 2; i++) await page.request.post(`/api/v1/training-sessions/${original.id}/messages/complete`, { headers, data: { content: answer } })
  await page.request.post(`/api/v1/training-sessions/${original.id}/finish`, { headers })
  await page.goto(`/training/${original.id}`)
  const restarted = page.waitForResponse((r) => r.url().endsWith(`/${original.id}/restart`))
  await page.getByRole('button', { name: '同场景重新开始', exact: true }).click()
  const current = (await (await restarted).json()).data
  expect(current.depth).toBe('PRESSURE')
  await expect(page).toHaveURL(new RegExp(`/training/${current.id}$`))
  await page.getByLabel('输入面试回答').fill(answer)
  const sent = page.waitForResponse((r) => r.url().endsWith(`/${current.id}/messages/complete`))
  await page.getByRole('button', { name: '发送回答', exact: true }).click()
  expect((await sent).status()).toBe(200)
})

test('已登录时可以打开验证和教练分享链接', async ({ page }) => {
  const headers = await register(page)
  await page.goto('/verify-email?token=invalid-test-token')
  await expect(page).toHaveURL(/\/verify-email\?token=/)
  await expect(page.getByRole('heading', { name: '验证没成功' })).toBeVisible()
  const created = await page.request.post('/api/v1/training-sessions', { headers, data: { sceneId: 'scene-interview-03' } })
  const current = (await created.json()).data
  const share = await page.request.post(`/api/v1/share/training-sessions/${current.id}`, { headers })
  expect(share.status()).toBe(200)
  await page.goto((await share.json()).data.url)
  await expect(page).toHaveURL(/\/share\//)
  await expect(page.getByText('教练查看 · 只读', { exact: true })).toBeVisible()
})

test('训练记录中的语音准备会话恢复到语音页', async ({ page }) => {
  const headers = await register(page)
  const created = await page.request.post('/api/v1/training-sessions/prepare', { headers, multipart: { sceneId: 'scene-interview-03', channel: 'VOICE', depth: 'THREE_LAYER' } })
  const current = (await created.json()).data
  await page.goto('/history')
  await page.getByRole('button', { name: '继续训练 →', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/voice\\?.*sessionId=${current.id}`))
  await expect(page.getByRole('button', { name: '三层深挖', exact: true })).toBeDisabled()
})

test('删除原训练后计划不会误用另一场评分报告', async ({ page }) => {
  const headers = await register(page)
  async function complete(sceneId: string) {
    const created = await page.request.post('/api/v1/training-sessions', { headers, data: { sceneId } })
    const id = (await created.json()).data.id
    for (let i = 0; i < 2; i++) await page.request.post(`/api/v1/training-sessions/${id}/messages/complete`, { headers, data: { content: answer } })
    expect((await page.request.post(`/api/v1/training-sessions/${id}/finish`, { headers })).status()).toBe(200)
    return id
  }
  const originalId = await complete('scene-interview-03')
  const plan = (await (await page.request.get('/api/v1/training-plans', { headers })).json()).data[0]
  await complete('scene-interview-01')
  expect((await page.request.delete(`/api/v1/training-sessions/${originalId}`, { headers })).status()).toBe(204)
  await page.goto(`/plans/${plan.id}`)
  await expect(page.getByText('原训练记录已删除或未关联', { exact: false })).toBeVisible()
  await expect(page.locator('a.report-link')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '确认已复盘', exact: true })).toBeDisabled()
})

for (const engine of ['pipeline', 'doubao']) {
test(`语音回答对应原题、录制收尾与评分重试（${engine}）`, async ({ page }) => {
  const headers = await register(page)
  const created = await page.request.post('/api/v1/training-sessions/prepare', { headers, multipart: { sceneId: 'scene-interview-03', channel: 'VOICE' } })
  const current = (await created.json()).data
  await page.addInitScript(() => {
    class FakeSocket {
      static OPEN = 1
      readyState = 1
      onopen: ((event: Event) => void) | null = null
      onmessage: ((event: { data: string }) => void) | null = null
      onclose: ((event: { code: number }) => void) | null = null
      constructor() { (window as any).__auditSocket = this; setTimeout(() => this.onopen?.(new Event('open')), 0) }
      send() {}
      close() { this.readyState = 3; this.onclose?.({ code: 1000 }) }
    }
    class FakeRecorder extends EventTarget {
      static isTypeSupported() { return true }
      state = 'inactive'
      ondataavailable: ((event: { data: Blob }) => void) | null = null
      constructor() { super(); (window as any).__auditRecorder = this }
      start() { this.state = 'recording' }
      stop() { this.state = 'inactive'; setTimeout(() => { this.ondataavailable?.({ data: new Blob(['AUDIT_FINAL_RECORDING_CHUNK']) }); this.dispatchEvent(new Event('stop')) }, 20) }
    }
    Object.defineProperty(window, 'WebSocket', { value: FakeSocket })
    Object.defineProperty(window, 'MediaRecorder', { value: FakeRecorder })
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: async () => {
      const audio = new AudioContext()
      const output = audio.createMediaStreamDestination()
      const oscillator = audio.createOscillator()
      oscillator.connect(output)
      oscillator.start()
      return output.stream
    } })
  })
  await page.route('**/api/v1/voice/status', (route) => route.fulfill({ json: { data: { enabled: true, engine, voice: 'test-voice' }, meta: {} } }))
  let saves = 0
  let scores = 0
  let turns: Array<{ question: string; answer: string }> = []
  let hasFinalChunk = false
  await page.route('**/api/v1/voice/sessions', async (route) => {
    saves++
    const body = route.request().postDataBuffer()!.toString('utf8')
    hasFinalChunk = body.includes('AUDIT_FINAL_RECORDING_CHUNK')
    turns = JSON.parse(body.match(/name="turns"\r\n\r\n([\s\S]*?)\r\n--/)![1])
    await route.fulfill({ json: { data: { id: current.id }, meta: {} } })
  })
  await page.route(`**/api/v1/training-sessions/${current.id}/finish`, async (route) => {
    scores++
    await route.fulfill(scores === 1 ? { status: 503, json: { detail: '评分暂时不可用' } } : { json: { data: {}, meta: {} } })
  })
  await page.goto(`/voice?sceneId=scene-interview-03&sessionId=${current.id}`)
  await page.getByRole('button', { name: '开始面试', exact: true }).click()
  await page.waitForFunction(() => (window as any).__auditRecorder?.state === 'recording')
  await page.evaluate((engine) => {
    const socket = (window as any).__auditSocket
    const emit = (type: string, text?: string) => socket.onmessage({ data: JSON.stringify({ type, text, transcript: text }) })
    if (engine === 'pipeline') {
      emit('assistant_delta', '请介绍你的项目职责。'); emit('assistant_end')
      emit('user', '我负责接口设计。'); emit('assistant_delta', '怎么验证结果？'); emit('assistant_end')
      emit('user', '对比监控指标。'); emit('assistant_delta', '有什么边界？'); emit('assistant_end')
    } else {
      emit('response.output_text.done', '请介绍你的项目职责。')
      emit('conversation.item.input_audio_transcription.completed', '我负责接口设计。'); emit('response.output_text.done', '怎么验证结果？')
      emit('conversation.item.input_audio_transcription.completed', '对比监控指标。'); emit('response.output_text.done', '有什么边界？')
    }
  }, engine)
  await page.locator('.room-controls .end').click()
  await expect(page.getByRole('button', { name: '重试生成报告', exact: true })).toBeVisible()
  expect(hasFinalChunk).toBe(true)
  expect(turns).toEqual([{ question: '请介绍你的项目职责。', answer: '我负责接口设计。' }, { question: '怎么验证结果？', answer: '对比监控指标。' }].map((item) => expect.objectContaining(item)))
  await page.getByRole('button', { name: '重试生成报告', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/report/${current.id}$`))
  expect(saves).toBe(1)
  expect(scores).toBe(2)
})

}
