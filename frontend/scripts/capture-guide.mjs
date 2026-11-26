
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const API = 'http://127.0.0.1:8081/api/v1'
const WEB = 'http://localhost:5173'
const OUT = path.resolve('..', 'docs', 'screenshots', 'guide')
mkdirSync(OUT, { recursive: true })

async function apiLogin(email, password) {
  const res = await fetch(API + '/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const json = await res.json()
  return json.data.accessToken
}
async function api(token, p) {
  const res = await fetch(API + p, { headers: { Authorization: 'Bearer ' + token } })
  return res.json().catch(() => ({}))
}

const student = await apiLogin('student@example.com', 'Student123!')
const admin = await apiLogin('admin@example.com', 'Admin123!')

const sessions = (await api(student, '/training-sessions?limit=50')).data || []
const finished = sessions.find(s => s.status === 'FINISHED')
let live = sessions.find(s => s.status === 'IN_PROGRESS')
if (!live) {
  const sceneId = sessions[0]?.sceneId || 'scene-interview-01'
  const r = await fetch(API + '/training-sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + student },
    body: JSON.stringify({ sceneId, channel: 'TEXT' }),
  })
  const j = await r.json()
  live = j.data ? { id: j.data.id, created: true } : null
  console.log('created live session:', JSON.stringify(j).slice(0, 200))
}
const plans = (await api(student, '/training-plans')).data || []
const learners = (await api(admin, '/admin/learners')).data || []

console.log(JSON.stringify({
  finishedId: finished?.id, liveId: live?.id, planId: plans[0]?.id,
  learnerCount: Array.isArray(learners) ? learners.length : 'n/a',
  learnerSample: JSON.stringify(learners).slice(0, 200),
}))

const browser = await chromium.launch({
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
})
const shots = []

async function shoot(ctxUser, label, pages, outPrefix) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: 'zh-CN' })
  const page = await ctx.newPage()
  const creds = ctxUser === 'admin'
    ? { email: 'admin@example.com', password: 'Admin123!' }
    : { email: 'student@example.com', password: 'Student123!' }
  await page.goto(WEB + '/login', { waitUntil: 'networkidle' })
  await page.getByRole('textbox', { name: '邮箱' }).fill(creds.email)
  await page.getByRole('textbox', { name: '密码' }).fill(creds.password)
  await page.getByRole('button', { name: '进入训练空间' }).click()
  await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 }).catch(() => {})
  await page.waitForLoadState('networkidle').catch(() => {})
  for (const [slug, pathname, opts] of pages) {
    const file = path.join(OUT, outPrefix + slug + '.png')
    await page.goto(WEB + pathname, { waitUntil: 'domcontentloaded' }).catch(e => console.log('goto fail', pathname, e.message))
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(opts?.wait ?? 1200)
    await page.screenshot({ path: file, fullPage: opts?.full ?? true })
    shots.push({ slug: outPrefix + slug, path: pathname, file, title: await page.title() })
    console.log('shot', outPrefix + slug, pathname)
  }
  await ctx.close()
}

await shoot('student', 'student', [
  ['login', '/login', { full: false }],
  ['dashboard', '/'],
  ['scenes', '/scenes'],
  ['training', '/training/' + live?.id],
  ['report', '/report/' + finished?.id],
  ['history', '/history'],
  ['plans', '/plans'],
  ['plan-detail', '/plans/' + plans[0]?.id],
  ['scripts', '/scripts'],
  ['saved-scripts', '/scripts/saved'],
  ['favorites', '/favorites'],
  ['profile', '/profile'],
  ['voice', '/voice', { full: false, wait: 2000 }],
  ['video', '/video', { full: false, wait: 2500 }],
  ['privacy', '/privacy'],
  ['plan-lesson', '/plan-lesson'],
], '')

await shoot('admin', 'admin', [
  ['admin', '/admin'],
  ['admin-learner', '/admin/learners/' + (Array.isArray(learners) ? learners[0]?.id : '')],
], 'admin-')

await browser.close()
console.log('DONE', shots.length)
