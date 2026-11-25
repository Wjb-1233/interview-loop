import { expect, test } from '@playwright/test'

test('数字人默认顺序保持，开发形象选择优先且生产忽略 URL 覆盖', async ({ page }) => {
  await page.goto('/login')
  const orders = await page.evaluate(async () => {
    const moduleUrl = '/src/lib/avatarConfig.ts'
    const { avatarOrder } = await import(/* @vite-ignore */ moduleUrl)
    return {
      defaults: avatarOrder('auto', false, ''),
      local: avatarOrder('live2d', false, ''),
      dev: avatarOrder('auto', true, '?avatar=vrm'),
      production: avatarOrder('photo', false, '?avatar=human'),
      invalid: avatarOrder('unrecognized', false, ''),
    }
  })
  expect(orders.defaults).toEqual(['simli', 'human', 'photo', 'live2d'])
  expect(orders.local[0]).toBe('live2d')
  expect(orders.dev[0]).toBe('vrm')
  expect(orders.production[0]).toBe('photo')
  expect(orders.invalid).toEqual(orders.defaults)
  expect(new Set(orders.dev).size).toBe(orders.dev.length)
})
