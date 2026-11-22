import { expect, test, type Page } from '@playwright/test'

async function mockAccount(page: Page) {
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const data = path.endsWith('/auth/refresh')
      ? { accessToken: 'desktop-test', user: { id: 'desktop-user', email: 'desktop@example.com', displayName: '桌面验收', role: 'STUDENT', emailVerified: true, bio: null, avatar: null } }
      : path.endsWith('/mistakes') ? { items: [], total: 0 } : []
    return route.fulfill({ json: { data, meta: {} } })
  })
}

test('桌面布局保留完整侧栏、折叠和导航，页面没有安装元数据', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockAccount(page)
  await page.goto('/scripts/saved')
  await expect(page.getByRole('heading', { name: '我的话术库', exact: true })).toBeVisible()
  await expect(page.locator('link[rel="manifest"], link[rel="apple-touch-icon"], meta[name="mobile-web-app-capable"], meta[name^="apple-mobile"]')).toHaveCount(0)
  const content = page.locator('.shell .content')
  const before = (await content.boundingBox())!.width
  const toggle = page.getByRole('button', { name: '切换导航', exact: true })
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect.poll(async () => (await content.boundingBox())!.width).toBeGreaterThan(before + 100)
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await page.getByRole('navigation', { name: '学员导航', exact: true }).getByRole('link', { name: '话术优化', exact: true }).click()
  await expect(page).toHaveURL(/\/scripts$/)
  await expect(page.locator('.topbar-account strong')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('退出旧缓存只处理本应用，桌面断网提示仍可正常恢复', async ({ page }) => {
  await page.addInitScript(() => {
    const observed = { unregister: [] as string[], deleted: [] as string[] }
    ;(window as any).__cacheRetirement = observed
    const makeRegistration = (scope: string, script: string) => ({ scope: location.origin + scope, active: { scriptURL: location.origin + script }, waiting: null, installing: null, unregister: async () => { observed.unregister.push(scope); return true } })
    Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { getRegistrations: async () => [makeRegistration('/', '/sw.js'), makeRegistration('/other/', '/other/worker.js')] } })
    Object.defineProperty(window, 'caches', { configurable: true, value: { keys: async () => ['yanjie-pwa-v2-static', 'yanjie-pwa-v2-runtime', 'other-app-data'], delete: async (name: string) => { observed.deleted.push(name); return true } } })
  })
  await mockAccount(page)
  await page.goto('/scripts/saved')
  await expect.poll(() => page.evaluate(() => (window as any).__cacheRetirement)).toEqual({ unregister: ['/'], deleted: ['yanjie-pwa-v2-static', 'yanjie-pwa-v2-runtime'] })
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  await expect(page.getByRole('status')).toContainText('网络连接已断开')
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(page.getByRole('status')).toHaveCount(0)
})
