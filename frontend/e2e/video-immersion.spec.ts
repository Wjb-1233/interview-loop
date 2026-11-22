import { expect, test, type Page } from '@playwright/test'

type Engine = 'pipeline' | 'doubao'

async function openRoom(page: Page, engine: Engine = 'pipeline', failRoomCamera = false, mode: 'voice' | 'video' = 'video') {
  const errors: string[] = []
  const saved: string[] = []
  const discarded: string[] = []
  let scores = 0
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(({ failRoomCamera }) => {
    class FakeSocket {
      static OPEN = 1
      readyState = 1
      sent: unknown[] = []
      onopen: ((event: Event) => void) | null = null
      onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null
      onclose: ((event: { code: number }) => void) | null = null
      constructor() {
        ;(window as any).__videoSocket = this
        setTimeout(() => this.onopen?.(new Event('open')), 0)
      }
      send(data: unknown) { this.sent.push(data) }
      close() {
        if (this.readyState === 3) return
        this.readyState = 3
        setTimeout(() => this.onclose?.({ code: 1000 }), 0)
      }
    }
    class FakeRecorder extends EventTarget {
      static isTypeSupported() { return true }
      state = 'inactive'
      ondataavailable: ((event: { data: Blob }) => void) | null = null
      constructor() { super(); (window as any).__videoRecorder = this }
      start() { this.state = 'recording' }
      stop() {
        this.state = 'inactive'
        setTimeout(() => {
          this.ondataavailable?.({ data: new Blob(['INTERVIEW_FINAL_CHUNK']) })
          this.dispatchEvent(new Event('stop'))
        }, 20)
      }
    }
    Object.defineProperty(window, 'WebSocket', { value: FakeSocket })
    Object.defineProperty(window, 'MediaRecorder', { value: FakeRecorder })
    let requests = 0
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: async () => {
      requests++
      if (failRoomCamera && requests > 1) throw new DOMException('camera busy', 'NotReadableError')
      const audio = new AudioContext()
      const output = audio.createMediaStreamDestination()
      const oscillator = audio.createOscillator()
      oscillator.connect(output)
      oscillator.start()
      const canvas = document.createElement('canvas')
      canvas.width = 640; canvas.height = 400
      const context = canvas.getContext('2d')!
      const draw = () => {
        context.fillStyle = '#aec6d4'; context.fillRect(0, 0, 640, 400)
        context.fillStyle = '#496777'; context.beginPath(); context.arc(320, 170, 64, 0, Math.PI * 2); context.fill()
        context.beginPath(); context.ellipse(320, 380, 128, 130, 0, 0, Math.PI * 2); context.fill()
      }
      draw(); setInterval(draw, 100)
      return new MediaStream([...canvas.captureStream(10).getVideoTracks(), ...output.stream.getAudioTracks()])
    } })
    Object.defineProperty(window, 'speechSynthesis', { value: {
      cancel() { (window as any).__replayUtterance?.onend?.(); (window as any).__replayUtterance = null },
      speak(utterance: SpeechSynthesisUtterance) { (window as any).__replayUtterance = utterance; utterance.onstart?.(new SpeechSynthesisEvent('start', { utterance })) },
    } })
  }, { failRoomCamera })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path.endsWith('/auth/refresh')) data = { accessToken: 'video-test', user: { id: 'test', displayName: '视频验收', role: 'STUDENT' } }
    else if (path.endsWith('/scenes')) data = [{ id: 'video-scene', title: '项目经历面试', roleName: '面试官', category: '求职面试', openingLine: '请介绍你的项目职责。' }]
    else if (path.endsWith('/voice/status')) data = { enabled: true, engine, voice: 'test-voice' }
    else if (path.endsWith('/interview-context')) data = { instructions: '中文面试', openingLine: '请介绍你的项目职责。', minimumRounds: 2 }
    else if (path.endsWith('/voice/ws-ticket')) data = { ticket: 'test-ticket', expiresIn: 60 }
    else if (path.endsWith('/discard')) { discarded.push(path); await route.fulfill({ status: 204 }); return }
    else if (path.endsWith('/voice/sessions')) { saved.push(route.request().postDataBuffer()!.toString('utf8')); data = { id: 'video-session' } }
    else if (path.endsWith('/finish')) {
      scores++
      if (scores === 1) { await route.fulfill({ status: 503, json: { detail: '评分暂时不可用' } }); return }
      data = {}
    } else { await route.fulfill({ status: 404, json: { detail: '此测试未提供该接口' } }); return }
    await route.fulfill({ json: { data, meta: {} } })
  })
  await page.goto(`/${mode}?sceneId=video-scene&sessionId=video-session`)
  if (mode === 'video') await page.getByRole('button', { name: '开启摄像头和麦克风', exact: true }).click()
  await expect(page.getByRole('button', { name: '开始面试', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '开始面试', exact: true }).click()
  if (mode === 'video') await expect(page.getByRole('dialog', { name: '视频面试室', exact: true })).toBeVisible()
  if (!failRoomCamera) await page.waitForFunction(() => (window as any).__videoRecorder?.state === 'recording')
  return { errors, saved, discarded, scores: () => scores }
}

// 面试官有三种形象实现：照片（.photo-stage）、VRM 3D（.vrm-presenter）、Live2D（canvas）。
// 按实际渲染的模式断言同一件事：面试官画面已渲染且可被读屏识别。
async function expectPresenterSurface(page: Page) {
  const host = page.locator('.avatar-presenter')
  await expect(host).toBeVisible()
  const photo = host.locator('.photo-stage')
  const vrm = host.locator('.vrm-presenter')
  if (await photo.count()) {
    await expect(photo).toBeVisible()
    await expect(page.getByRole('img', { name: '虚拟面试官', exact: true })).toBeVisible()
  } else if (await vrm.count()) {
    await expect(vrm).toBeVisible()
    await expect(page.getByRole('img', { name: '虚拟面试官 · VRM 3D', exact: true })).toBeVisible()
  } else {
    await expect(host.locator('.avatar-canvas canvas')).toHaveCount(1)
  }
}

async function sendAudio(page: Page, engine: Engine, seconds = 1) {
  await page.evaluate(({ engine, seconds }) => {
    const samples = new Int16Array(24000 * seconds)
    for (let i = 0; i < samples.length; i++) samples[i] = Math.sin(i / 20) * 4000
    const socket = (window as any).__videoSocket
    if (engine === 'pipeline') socket.onmessage({ data: samples.buffer })
    else {
      let binary = ''
      for (const byte of new Uint8Array(samples.buffer)) binary += String.fromCharCode(byte)
      socket.onmessage({ data: JSON.stringify({ type: 'response.output_audio.delta', delta: btoa(binary) }) })
    }
  }, { engine, seconds })
}

async function sendConversation(page: Page, engine: Engine) {
  await page.evaluate((engine) => {
    const socket = (window as any).__videoSocket
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
}

for (const engine of ['pipeline', 'doubao'] as const) {
  test(`视频沉浸画面、语音动画与隐藏转写后仍可保存评分（${engine}）`, async ({ page }) => {
    const state = await openRoom(page, engine)
    const art = page.getByRole('group', { name: '虚拟面试官', exact: true })
    await expect(art).toBeVisible()
    await expect(page.locator('.live-transcript')).toHaveCount(0)
    await page.evaluate(() => { (window as any).__cameraTrack = (document.querySelector('.room-self') as HTMLVideoElement).srcObject })
    await page.getByRole('button', { name: '退出沉浸', exact: true }).click()
    await page.getByRole('button', { name: '沉浸模式', exact: true }).click()
    expect(await page.evaluate(() => (document.querySelector('.room-self') as HTMLVideoElement).srcObject === (window as any).__cameraTrack)).toBe(true)
    await expect(page.locator('.room-self')).toBeVisible()
    await sendAudio(page, engine)
    await expect(art).toHaveClass(/speaking/)
    await expect(art).not.toHaveClass(/speaking/)
    await sendAudio(page, engine, 4)
    await expect(art).toHaveClass(/speaking/)
    await page.getByRole('button', { name: '打断', exact: true }).click()
    await expect(art).not.toHaveClass(/speaking/)
    await sendConversation(page, engine)
    for (const text of ['请介绍你的项目职责。', '我负责接口设计。', '怎么验证结果？', '对比监控指标。', '有什么边界？']) {
      await expect(page.getByText(text, { exact: true })).toHaveCount(0)
    }
    await page.getByRole('button', { name: '重听问题', exact: true }).click()
    await expect(art).toHaveClass(/speaking/)
    expect(await page.evaluate(() => (window as any).__replayUtterance.text)).toBe('有什么边界？')
    await page.getByRole('button', { name: '打断', exact: true }).click()
    await expect(art).not.toHaveClass(/speaking/)
    if (engine === 'pipeline') await page.screenshot({ path: '../docs/evidence/video-immersive-desktop.png' })
    await page.locator('.room-controls .end').click()
    await expect(page.getByRole('button', { name: '重试生成报告', exact: true })).toBeVisible()
    const body = state.saved[0]!
    expect(body).toContain('INTERVIEW_FINAL_CHUNK')
    expect(body).toContain('name="video"')
    expect(body).toContain('name="channelHint"\r\n\r\nVIDEO')
    const turns = JSON.parse(body.match(/name="turns"\r\n\r\n([\s\S]*?)\r\n--/)![1]!)
    expect(turns).toEqual([
      expect.objectContaining({ question: '请介绍你的项目职责。', answer: '我负责接口设计。' }),
      expect.objectContaining({ question: '怎么验证结果？', answer: '对比监控指标。' }),
    ])
    await page.getByRole('button', { name: '重试生成报告', exact: true }).click()
    await expect(page).toHaveURL(/\/report\/video-session$/)
    expect(await page.evaluate(() => (window as any).__cameraTrack.getTracks().every((track: MediaStreamTrack) => track.readyState === 'ended'))).toBe(true)
    expect(state.saved).toHaveLength(1)
    expect(state.scores()).toBe(2)
    expect(state.errors).toEqual([])
  })
}

test('减少动画设置和沉浸模式键盘操作有效', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const state = await openRoom(page)
  const controls = await page.locator('.room-controls').boundingBox()
  expect(controls!.y + controls!.height).toBeLessThanOrEqual(720)
  await expectPresenterSurface(page)
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true)
  await sendAudio(page, 'pipeline')
  await expect(page.locator('.avatar-presenter')).toHaveClass(/speaking/)
  await page.locator('.room-controls .end').focus()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: '退出沉浸', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: '沉浸模式', exact: true })).toBeVisible()
  expect(state.errors).toEqual([])
})

test('共享播放逻辑保留纯语音面试和录音保存', async ({ page }) => {
  const state = await openRoom(page, 'pipeline', false, 'voice')
  await expect(page.locator('.room')).toBeVisible()
  await expect(page.locator('.interviewer-art, .live-transcript, .room-self')).toHaveCount(0)
  await sendAudio(page, 'pipeline', 4)
  await expect(page.locator('.voice-status')).toHaveText('面试官正在说…')
  await page.getByRole('button', { name: '打断', exact: true }).click()
  await sendConversation(page, 'pipeline')
  await expect(page.getByText('我负责接口设计。', { exact: true })).toHaveCount(0)
  await page.locator('.room-controls .end').click()
  await expect(page.getByRole('button', { name: '重试生成报告', exact: true })).toBeVisible()
  expect(state.saved[0]).toContain('name="audio"')
  expect(state.saved[0]).toContain('name="channelHint"\r\n\r\nVOICE')
  expect(state.errors).toEqual([])
})

for (const mode of ['voice', 'video'] as const) {
  test(`${mode} 作答后直接退出会清理准备会话，停止设备且不保存音视频`, async ({ page }) => {
    const state = await openRoom(page, 'pipeline', false, mode)
    await sendConversation(page, 'pipeline')
    await page.getByRole('link', { name: '直接退出', exact: true }).click()
    await expect(page).toHaveURL(/\/scenes$/)
    expect(state.discarded).toEqual(['/api/v1/training-sessions/video-session/discard'])
    expect(state.saved).toHaveLength(0)
    expect(state.scores()).toBe(0)
    expect(state.errors).toEqual([])
  })
}

for (const engine of ['pipeline', 'doubao'] as const) {
  test(`${engine} 只有一段作答且面试官尚未回复，也能结束并保存该回答`, async ({ page }) => {
    const state = await openRoom(page, engine)
    await page.evaluate(engine => {
      const event = engine === 'pipeline' ? { type: 'user', text: '我通过监控验证接口延迟。' } : { type: 'conversation.item.input_audio_transcription.delta', delta: '我通过监控验证接口延迟。' }
      ;(window as any).__videoSocket.onmessage({ data: JSON.stringify(event) })
    }, engine)
    await page.locator('.room-controls .end').click()
    await expect(page.getByRole('button', { name: '重试生成报告', exact: true })).toBeVisible()
    const turns = JSON.parse(state.saved[0]!.match(/name="turns"\r\n\r\n([\s\S]*?)\r\n--/)![1]!)
    expect(turns).toEqual([expect.objectContaining({ answer: '我通过监控验证接口延迟。' })])
    expect(state.discarded).toHaveLength(0)
    expect(state.scores()).toBe(1)
  })
}

test('沉浸模式中设备异常仍能显示恢复入口', async ({ page }) => {
  const state = await openRoom(page, 'pipeline', true)
  await expect(page.getByRole('alert')).toContainText('被其他程序占用')
  await expect(page.getByRole('button', { name: '重新申请权限', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '改用语音面试', exact: true })).toBeVisible()
  await expect(page.locator('.interviewer-art')).not.toHaveClass(/active|speaking/)
  expect(state.errors).toEqual([])
})

test('本地 Live2D 读取实际播放音轨，重听打断保留声音与评分且不调用云端数字人', async ({ page }) => {
  let cloudRequests = 0
  page.on('request', (request) => { if (request.url().includes('/api/v1/avatars/')) cloudRequests++ })
  await page.addInitScript(() => {
    const original = AnalyserNode.prototype.getFloatTimeDomainData
    AnalyserNode.prototype.getFloatTimeDomainData = function(array) {
      original.call(this, array)
      if (Array.from(array).some((value) => Math.abs(value) > .01)) (window as any).__avatarAudioObserved = true
    }
  })
  const state = await openRoom(page)
  await expect(page.locator('.avatar-presenter')).toHaveClass(/connected/)
  await sendAudio(page, 'pipeline', 4)
  await expect(page.locator('.avatar-presenter')).toHaveClass(/speaking/)
  await expect.poll(() => page.evaluate(() => Boolean((window as any).__avatarAudioObserved))).toBe(true)
  await page.screenshot({ path: '../docs/evidence/video-immersive-local-speaking.png' })
  await page.getByRole('button', { name: '打断', exact: true }).click()
  await expect(page.locator('.avatar-presenter')).not.toHaveClass(/speaking/)
  await sendConversation(page, 'pipeline')
  await page.getByRole('button', { name: '重听问题', exact: true }).click()
  await expect(page.locator('.avatar-presenter')).toHaveClass(/speaking/)
  expect(await page.evaluate(() => (window as any).__replayUtterance.text)).toBe('有什么边界？')
  await page.getByRole('button', { name: '打断', exact: true }).click()
  await expect(page.locator('.avatar-presenter')).not.toHaveClass(/speaking/)
  await expectPresenterSurface(page)
  await page.locator('.room-controls .end').click()
  await expect(page.getByRole('button', { name: '重试生成报告', exact: true })).toBeVisible()
  expect(state.saved[0]).toContain('我负责接口设计。')
  expect(state.saved[0]).toContain('请介绍你的项目职责。')
  expect(state.saved).toHaveLength(1)
  expect(cloudRequests).toBe(0)
  expect(state.errors).toEqual([])
})
