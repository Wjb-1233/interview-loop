import { expect, test, type Page } from '@playwright/test'

async function mockLibrary(page: Page) {
  const calls = { previews: 0, favorites: 0, deletions: 0 }
  const versions = Array.from({ length: 3 }, (_, i) => ({ id: `test-script-${i}`, sceneId: null, style: ['正式', '亲和', '简洁'][i], original: '我负责接口设计。', content: `第 ${i + 1} 个话术内容。`, highlights: [], favorite: false, createdAt: null }))
  let releasePreview: (() => void) | undefined
  let releaseFavorite: (() => void) | undefined
  const previewGate = new Promise<void>((resolve) => { releasePreview = resolve })
  const favoriteGate = new Promise<void>((resolve) => { releaseFavorite = resolve })
  let previewStatus = 200
  await page.addInitScript(() => {
    class FakeAudio {
      onended: (() => void) | null = null
      onerror: (() => void) | null = null
      constructor() { (window as any).__testAudio = this }
      async play() {
        if ((window as any).__rejectAudio) throw new Error('NotAllowedError')
      }
      pause() { (window as any).__audioPauses = ((window as any).__audioPauses || 0) + 1 }
    }
    Object.defineProperty(window, 'Audio', { value: FakeAudio })
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    let data: unknown = []
    if (path === '/auth/refresh') data = { accessToken: 'test-token', user: { id: 'test-user', email: 'test@example.com', displayName: '按钮验收', role: 'STUDENT', bio: null, avatar: null, emailVerified: true } }
    else if (path === '/scripts/preview') {
      calls.previews++
      await previewGate
      return route.fulfill(previewStatus === 200 ? { json: { data: { url: '/media/test.mp3' } } } : { status: 504, json: { title: 'PREVIEW_TIMEOUT', detail: '试听语音生成超时，请稍后重试。' } })
    } else if (path.endsWith('/favorite')) {
      calls.favorites++
      await favoriteGate
      data = { favorite: true }
    } else if (path.startsWith('/scripts/') && route.request().method() === 'DELETE') {
      calls.deletions++
      return route.fulfill({ status: 204 })
    } else if (path === '/scripts/generate') data = { versions, coachNote: '测试', degraded: false }
    else if (path === '/scripts') data = versions
    else if (path === '/training-sessions/mistakes') data = { items: [], total: 0 }
    return route.fulfill({ json: { data, meta: {} } })
  })
  return { calls, releasePreview: () => releasePreview!(), releaseFavorite: () => releaseFavorite!(), failPreview: () => { previewStatus = 504 } }
}

test('话术库试听等待时仍可收藏和删除，重复收藏不会发出多次请求', async ({ page }) => {
  const mock = await mockLibrary(page)
  await page.goto('/scripts/saved')
  const first = page.locator('.version-card').first()
  await first.getByRole('button', { name: '▶ 试听', exact: true }).click()
  await expect(first.getByRole('button', { name: '语音生成中…', exact: true })).toBeDisabled()
  await first.getByRole('button', { name: '☆ 收藏', exact: true }).click()
  await expect(first.getByRole('button', { name: '保存中…', exact: true })).toBeDisabled()
  expect(mock.calls.favorites).toBe(1)
  mock.releaseFavorite()
  await expect(first.getByRole('button', { name: '★ 已收藏', exact: true })).toBeEnabled()
  page.once('dialog', (dialog) => dialog.accept())
  await page.locator('.version-card').nth(1).getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.locator('.version-card')).toHaveCount(2)
  expect(mock.calls.deletions).toBe(1)
  mock.releasePreview()
  await expect(first.getByRole('button', { name: '■ 停止', exact: true })).toBeVisible()
  await first.getByRole('button', { name: '■ 停止', exact: true }).click()
  await expect(first.getByRole('button', { name: '▶ 试听', exact: true })).toBeEnabled()
  expect(mock.calls.previews).toBe(1)
})

test('试听超时给出具体提示，收藏成功清除旧错误', async ({ page }) => {
  const mock = await mockLibrary(page)
  mock.failPreview()
  mock.releasePreview()
  mock.releaseFavorite()
  await page.goto('/scripts/saved')
  const first = page.locator('.version-card').first()
  await first.getByRole('button', { name: '▶ 试听', exact: true }).click()
  await expect(page.locator('.error-banner')).toContainText('试听语音生成超时')
  await expect(page.locator('.error-banner')).not.toContainText('大模型')
  await expect(first.getByRole('button', { name: '▶ 试听', exact: true })).toBeEnabled()
  await first.getByRole('button', { name: '☆ 收藏', exact: true }).click()
  await expect(first.getByRole('button', { name: '★ 已收藏', exact: true })).toBeVisible()
  await expect(page.locator('.error-banner')).toHaveCount(0)
})

test('话术优化中播放被拒绝会提示，重试和离开页面会正确停止音频', async ({ page }) => {
  const mock = await mockLibrary(page)
  mock.releasePreview()
  mock.releaseFavorite()
  await page.goto('/scripts')
  await page.getByPlaceholder('例如：这个项目我负责后端，做了很多优化。').fill('我负责项目中的接口设计。')
  await page.getByRole('button', { name: '生成三种风格', exact: true }).click()
  const first = page.locator('.version-card').first()
  await first.getByRole('button', { name: '☆ 收藏', exact: true }).click()
  await expect(first.getByRole('button', { name: '★ 已收藏', exact: true })).toBeVisible()
  await page.evaluate(() => { (window as any).__rejectAudio = true })
  await first.getByRole('button', { name: '▶ 试听', exact: true }).click()
  await expect(page.locator('.error-banner')).toContainText('试听播放失败')
  await page.evaluate(() => { (window as any).__rejectAudio = false })
  await first.getByRole('button', { name: '▶ 试听', exact: true }).click()
  await expect(first.getByRole('button', { name: '■ 停止', exact: true })).toBeVisible()
  await expect(page.locator('.error-banner')).toHaveCount(0)
  const pauses = await page.evaluate(() => (window as any).__audioPauses || 0)
  await page.getByRole('link', { name: '话术库', exact: true }).click()
  await expect(page).toHaveURL(/\/scripts\/saved$/)
  expect(await page.evaluate(() => (window as any).__audioPauses)).toBe(pauses + 1)
})
