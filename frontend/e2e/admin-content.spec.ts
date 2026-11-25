import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'

async function mockAdmin(page: Page) {
  const scene = { id: 'scene-admin-test', category: '技术一面', title: '后端项目面试', industry: '互联网', position: '后端工程师', roleName: '技术面试官', difficulty: '中级', background: '围绕候选人的真实项目经历进行追问。', goal: '说明个人职责、技术方案和验证过程。', tags: ['项目'], openingLine: '请介绍你的项目。', coreIdea: '通过具体事实验证项目贡献', active: true, questionBank: Array.from({ length: 5 }, (_, i) => ({ text: `第 ${i + 1} 道原有问题，请说明实际依据。`, dimension: '信息完整', difficulty: '中级' })) }
  const courses = [{ id: 'course-test', title: '项目表达方法', dimension: '内容与逻辑', minutes: 15, description: '围绕真实项目讲清个人职责。', content: '先说明结论；提供个人行动与事实依据；说明结果、验证过程和适用边界。', active: true }]
  const savedScenes: Array<{ questionBank: Array<{ text: string; dimension: string | null; difficulty: string | null }> }> = []
  const savedCourses: Array<{ title: string; dimension: string; active: boolean }> = []
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const method = route.request().method()
    let data: unknown = []
    if (path === '/auth/refresh') data = { accessToken: 'admin-test-token', user: { id: 'admin-test', email: 'admin-test@example.com', displayName: '管理验收', role: 'ADMIN', emailVerified: true, bio: null, avatar: null } }
    else if (path === '/admin/overview') data = { users: 0, activeUsers: 0, scenes: 1, activeScenes: 1, courses: courses.length, activeCourses: courses.filter((item) => item.active).length, sessions: 0, averageScore: 0 }
    else if (path === `/admin/scenes/${scene.id}` && method === 'PATCH') {
      const payload = route.request().postDataJSON()
      savedScenes.push(payload)
      Object.assign(scene, payload)
      data = { id: scene.id, active: true }
    } else if (path === '/admin/scenes') data = [scene]
    else if (path === '/admin/courses' && method === 'POST') {
      const payload = route.request().postDataJSON()
      savedCourses.push(payload)
      courses.push({ ...payload, id: 'course-new' })
      data = { id: 'course-new' }
    } else if (path.startsWith('/admin/courses/') && method === 'PATCH') {
      const payload = route.request().postDataJSON()
      savedCourses.push(payload)
      Object.assign(courses.find((item) => path.endsWith(`/${item.id}`))!, payload)
      data = { id: path.split('/').pop() }
    } else if (path === '/admin/courses') data = courses
    else if (path === '/admin/question-coverage') data = { totalScenes: 1, scenesWithBank: 1, scenesWithoutBank: 0, totalQuestions: scene.questionBank.length, neverTrained: 1, items: [] }
    else if (path === '/admin/recordings') data = { count: 0, totalBytes: 0, totalMb: 0, retentionDays: 30 }
    else if (path === '/admin/tasks') data = [{ id: 'old-task', kind: 'VIDEO_INTERVIEW', status: 'DONE', progress: 100, stage: '完成', error: null, email: 'history@example.com', createdAt: '2026-11-01T00:00:00Z', updatedAt: '2026-11-01T01:00:00Z' }]
    return route.fulfill({ json: { data, meta: {} } })
  })
  await page.goto('/admin')
  await expect(page.getByRole('button', { name: '刷新数据', exact: true })).toBeEnabled()
  return { savedScenes, savedCourses, pageErrors }
}

test('旧分析结果只读保留，管理页不再提供重跑按钮', async ({ page }) => {
  const mock = await mockAdmin(page)
  await page.getByRole('button', { name: '历史分析记录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '历史分析记录', exact: true })).toBeVisible()
  await expect(page.locator('.tasks-table')).toContainText('history@example.com')
  await expect(page.getByRole('button', { name: /重跑|再跑一次/ })).toHaveCount(0)
  await expect(page.locator('.tasks-head')).toContainText('旧录像上传分析已停用')
  expect(mock.pageErrors).toEqual([])
})

test('题库合并到场景设计，超过三题和题目属性均完整保存', async ({ page }) => {
  const mock = await mockAdmin(page)
  await expect(page.getByRole('button', { name: '题库管理', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '场景设计', exact: true }).click()
  await page.getByRole('searchbox', { name: '搜索场景', exact: true }).fill('后端')
  await page.locator('.scene-card').getByRole('button', { name: '编辑', exact: true }).click()
  await expect(page.locator('.bank-row')).toHaveCount(5)
  await page.getByLabel('第 4 题正文', { exact: true }).fill('第四题修改后仍应保留，不能被截断。')
  await page.getByRole('button', { name: '+ 添加一题', exact: true }).click()
  await page.getByLabel('第 6 题正文', { exact: true }).fill('新增问题，请解释方案的边界条件。')
  await page.getByRole('combobox', { name: '第 6 题考察维度', exact: true }).click()
  await page.getByRole('option', { name: '贴合问题', exact: true }).click()
  await page.getByRole('combobox', { name: '第 6 题难度', exact: true }).click()
  await page.getByRole('option', { name: '进阶', exact: true }).click()
  await page.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect.poll(() => mock.savedScenes.length).toBe(1)
  expect(mock.savedScenes[0].questionBank).toHaveLength(6)
  expect(mock.savedScenes[0].questionBank[3]).toEqual({ text: '第四题修改后仍应保留，不能被截断。', dimension: '信息完整', difficulty: '中级' })
  expect(mock.savedScenes[0].questionBank[5]).toEqual({ text: '新增问题，请解释方案的边界条件。', dimension: '贴合问题', difficulty: '进阶' })
  await page.locator('.scene-card').getByRole('button', { name: '编辑', exact: true }).click()
  await expect(page.locator('.bank-row')).toHaveCount(6)
  expect(mock.pageErrors).toEqual([])
})

test('场景题目导入导出支持二十题，超限或损坏导入不覆盖原内容', async ({ page }) => {
  const mock = await mockAdmin(page)
  await page.getByRole('button', { name: '场景设计', exact: true }).click()
  await page.locator('.scene-card').getByRole('button', { name: '编辑', exact: true }).click()
  const questions = Array.from({ length: 20 }, (_, i) => ({ text: `导入第 ${i + 1} 道项目问题。`, dimension: '内容与逻辑', difficulty: '进阶' }))
  const input = page.getByLabel('导入场景题目', { exact: true })
  await input.setInputFiles({ name: 'questions.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(questions)) })
  await expect(page.locator('.bank-row')).toHaveCount(20)
  await expect(page.getByRole('button', { name: '+ 添加一题', exact: true })).toBeDisabled()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出', exact: true }).click()
  const download = await downloadPromise
  const exported = JSON.parse(await readFile((await download.path())!, 'utf8'))
  expect(exported).toEqual(questions)
  await input.setInputFiles({ name: 'overflow.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify([...questions, questions[0]])) })
  await expect(page.getByRole('alert')).toContainText('最多 20 道题')
  await expect(page.locator('.bank-row')).toHaveCount(20)
  await input.setInputFiles({ name: 'broken.json', mimeType: 'application/json', buffer: Buffer.from('[null]') })
  await expect(page.getByRole('alert')).toContainText('每道题需要 text 正文')
  await expect(page.getByLabel('第 20 题正文', { exact: true })).toHaveValue(questions[19].text)
  await page.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect.poll(() => mock.savedScenes.length).toBe(1)
  expect(mock.savedScenes[0].questionBank).toEqual(questions)
  expect(mock.pageErrors).toEqual([])
})

test('微课内容管理保留新增编辑停用，默认使用当前评分维度', async ({ page }) => {
  const mock = await mockAdmin(page)
  await expect(page.getByRole('button', { name: '微课素材', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '微课内容管理', exact: true }).click()
  await expect(page.getByRole('heading', { name: '微课内容管理', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '新增微课', exact: true }).click()
  await expect(page.getByRole('combobox', { name: '课程维度', exact: true })).toContainText('内容与逻辑')
  await page.getByLabel('课程名称', { exact: true }).fill('管理员新增课程底稿')
  await page.getByLabel(/课程正文（生成底稿）/).fill('先说明核心结论；引用真实项目事实与个人行动；最后提供验证结果和边界。')
  await page.getByRole('button', { name: '创建微课', exact: true }).click()
  await expect.poll(() => mock.savedCourses.length).toBe(1)
  expect(mock.savedCourses[0].dimension).toBe('内容与逻辑')
  const row = page.locator('.course-card').filter({ hasText: '管理员新增课程底稿' })
  await row.getByRole('button', { name: '编辑', exact: true }).click()
  await page.getByLabel('课程名称', { exact: true }).fill('管理员更新课程底稿')
  await page.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect.poll(() => mock.savedCourses.length).toBe(2)
  page.once('dialog', (dialog) => dialog.accept())
  await page.locator('.course-card').filter({ hasText: '管理员更新课程底稿' }).getByRole('button', { name: '停用', exact: true }).click()
  await expect.poll(() => mock.savedCourses.length).toBe(3)
  expect(mock.savedCourses[2].active).toBe(false)
  await expect(page.locator('.course-card').filter({ hasText: '管理员更新课程底稿' })).toContainText('已停用')
  await page.getByRole('button', { name: '题目覆盖', exact: true }).click()
  await expect(page.getByText('场景总数', { exact: true })).toBeVisible()
  expect(mock.pageErrors).toEqual([])
})
