import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dist = resolve(root, 'dist')
function assert(condition, message) {
  if (!condition) throw new Error(`Build verification failed: ${message}`)
}

const html = readFileSync(resolve(dist, 'index.html'), 'utf8')
assert(html.includes('type="module"'), 'application entry is missing')
assert(existsSync(resolve(dist, 'favicon.svg')), 'desktop favicon is missing')
assert(!html.includes('rel="manifest"') && !html.includes('apple-touch-icon'), 'retired install metadata must not ship')
const bundles = readdirSync(resolve(dist, 'assets')).filter((name) => name.endsWith('.js'))
assert(bundles.length > 0, 'application JavaScript is missing')
const javascript = bundles.map((name) => readFileSync(resolve(dist, 'assets', name), 'utf8')).join('\n')
for (const asset of ['live2dcubismcore.min.js', 'hiyori/Hiyori.model3.json', 'hiyori/Hiyori.moc3', 'hiyori/Hiyori.2048/texture_00.png', 'hiyori/Hiyori.2048/texture_01.png', 'LICENSE.md']) {
  assert(existsSync(resolve(dist, 'avatars/live2d', asset)), `local avatar asset is missing: ${asset}`)
}
assert(!javascript.includes('/avatars/ticket') && !javascript.includes('/avatars/ws'), 'retired paid avatar connection must not ship')
for (const credential of ['Student123!', 'Admin123!']) {
  assert(!javascript.includes(credential), 'demo credentials must not ship in production bundles')
}
console.log('Build verification passed: desktop assets and credential hygiene are valid.')
