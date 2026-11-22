import type { Application } from 'pixi.js'

export type LocalAvatar = {
  observeAudio: (source: AnalyserNode | null) => void
  setSpeaking: (value: boolean) => void
  setListening: (value: boolean) => void
  setActive: (value: boolean) => void
  destroy: () => void
}

let coreLoading: Promise<void> | null = null

function loadCore(): Promise<void> {
  if ((window as Window & { Live2DCubismCore?: unknown }).Live2DCubismCore) return Promise.resolve()
  if (coreLoading) return coreLoading
  coreLoading = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = '/avatars/live2d/live2dcubismcore.min.js'
    script.onload = () => resolve()
    script.onerror = () => { script.remove(); coreLoading = null; reject(new Error('Live2D runtime unavailable')) }
    document.head.append(script)
  })
  return coreLoading
}

/** 本地渲染；只读取播放音轨的音量，不负责播放或发送音频。 */
export async function createLocalAvatar(container: HTMLElement): Promise<LocalAvatar> {
  await loadCore()
  const [{ Application, Ticker }, { Live2DModel, MotionPreloadStrategy }] = await Promise.all([
    import('pixi.js'), import('pixi-live2d-display/cubism4'),
  ])
  Live2DModel.registerTicker(Ticker)
  const app: Application = new Application({
    width: Math.max(64, container.clientWidth), height: Math.max(64, container.clientHeight),
    backgroundAlpha: 0, antialias: true, autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2), powerPreference: 'low-power',
  })
  app.ticker.maxFPS = 30
  try {
    const model = await Live2DModel.from('/avatars/live2d/hiyori/Hiyori.model3.json', {
      autoInteract: false, autoUpdate: false, idleMotionGroup: '', motionPreload: MotionPreloadStrategy.NONE,
    })
    app.stage.addChild(model)
    container.append(app.view)
    model.anchor.set(.5, 0)
    let analyser: AnalyserNode | null = null
    let samples = new Float32Array(256)
    let speaking = false
    let listening = false
    let active = true
    let mouth = 0
    let elapsed = 0
    const reduced = matchMedia('(prefers-reduced-motion: reduce)')
    const internal = model.internalModel
    const core = internal.coreModel as { setParameterValueById: (id: string, value: number) => void }
    const resize = () => {
      const width = Math.max(64, container.clientWidth), height = Math.max(64, container.clientHeight)
      app.renderer.resize(width, height)
      const scale = Math.min(width / (internal.width * .38), height / (internal.height * .32))
      model.scale.set(scale)
      model.position.set(width / 2, -height * .10)
    }
    const observer = new ResizeObserver(resize)
    observer.observe(container)
    resize()
    internal.on('beforeModelUpdate', () => {
      const still = reduced.matches || !active
      core.setParameterValueById('ParamMouthOpenY', mouth)
      core.setParameterValueById('ParamMouthForm', .35)
      core.setParameterValueById('ParamAngleX', still ? 0 : Math.sin(elapsed * .55) * 2)
      core.setParameterValueById('ParamAngleY', still ? 0 : Math.sin(elapsed * .7) * (listening ? 1.4 : .7))
      core.setParameterValueById('ParamAngleZ', still ? 0 : Math.sin(elapsed * .38) * 1.2)
      core.setParameterValueById('ParamBodyAngleX', still ? 0 : Math.sin(elapsed * .35) * .8)
      if (still) {
        core.setParameterValueById('ParamBreath', .5)
        core.setParameterValueById('ParamEyeLOpen', 1)
        core.setParameterValueById('ParamEyeROpen', 1)
      }
    })
    app.ticker.add(() => {
      const dt = Math.min(100, app.ticker.deltaMS)
      elapsed += dt / 1000
      let target = 0
      if (analyser && analyser.context.state === 'running') {
        analyser.getFloatTimeDomainData(samples)
        let energy = 0
        for (const value of samples) energy += value * value
        target = Math.min(1, Math.max(0, (Math.sqrt(energy / samples.length) - .006) * 8))
      } else if (speaking) {
        // 浏览器语音后备无法取得音轨，仅按说话状态作辅助动作。
        target = .15 + Math.abs(Math.sin(elapsed * 11)) * .35
      }
      mouth += (target - mouth) * (1 - Math.exp(-dt / (target > mouth ? 45 : 85)))
      model.update(dt)
    })
    const visibility = () => { if (document.hidden) app.stop(); else app.start() }
    document.addEventListener('visibilitychange', visibility)
    visibility()
    return {
      observeAudio(source) {
        analyser = source
        if (source) samples = new Float32Array(source.fftSize)
        else mouth = 0
      },
      setSpeaking(value) { speaking = value },
      setListening(value) { listening = value },
      setActive(value) { active = value },
      destroy() {
        observer.disconnect()
        document.removeEventListener('visibilitychange', visibility)
        analyser = null
        app.destroy(true, { children: true, texture: true, baseTexture: true })
      },
    }
  } catch (error) {
    app.destroy(true, { children: true, texture: true, baseTexture: true })
    throw error
  }
}
