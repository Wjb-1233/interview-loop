import { expect, test } from '@playwright/test'

/** 侧边栏与模块调整：新入口存在，已删模块不再出现。 */

test('侧边栏入口与当前模块一致，自建场景整合到场景页', async ({ page }) => {
  const email = `nav-${Date.now()}@example.com`
  const password = 'NavE2E123!'

  await page.goto('/login')
  await page.getByRole('button', { name: '注册' }).first().click()
  await page.locator('input[name="displayName"]').fill('导航测试')
  await page.locator('input[name="email"]').fill(email)
  await page.locator('input[name="password"]').fill(password)
  await page.locator('input[name="confirmPassword"]').fill(password)
  await page.getByRole('checkbox', { name: '我已阅读并同意', exact: true }).check()
  await page.locator('button[type="submit"]').click()
  await expect(page.getByRole('link', { name: '场景训练' })).toBeVisible()

  await expect(page.getByRole('link', { name: '我的场景', exact: true })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '话术优化' })).toBeVisible()
  await page.getByRole('link', { name: '场景训练', exact: true }).click()
  await page.getByRole('button', { name: '我的场景', exact: true }).click()
  await expect(page.getByRole('button', { name: '新建场景', exact: true })).toBeVisible()

  for (const removed of ['通用练习', '故事库', '编程笔试', '简历诊断', '刷题', '群面']) {
    await expect(page.getByRole('link', { name: removed })).toHaveCount(0)
  }
})
