/** Captures the user's stream and owns the final MediaRecorder data boundary. */
export function useInterviewRecording() {
  let recorder: MediaRecorder | null = null
  let chunks: Blob[] = []
  let mimeType = 'audio/webm'
  function startRecording(stream: MediaStream, video: boolean): void {
    if (typeof MediaRecorder === 'undefined') return
    chunks = []
    const currentChunks = chunks
    mimeType = video ? 'video/webm' : 'audio/webm'
    const mime = video && MediaRecorder.isTypeSupported('video/webm;codecs=vp8,opus') ? 'video/webm;codecs=vp8,opus' : undefined
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
    recorder.ondataavailable = event => { if (event.data.size) currentChunks.push(event.data) }
    recorder.start(1000)
  }
  async function finishRecording(): Promise<void> {
    if (!recorder || recorder.state === 'inactive') return
    const current = recorder
    await new Promise<void>(resolve => {
      current.addEventListener('stop', () => resolve(), { once: true })
      current.stop()
    })
  }
  function stopRecording(): void {
    try { if (recorder && recorder.state !== 'inactive') recorder.stop() } catch { /* Already stopped. */ }
    recorder = null
  }
  return { startRecording, finishRecording, stopRecording,
    recordingBlob: () => chunks.length ? new Blob(chunks, { type: mimeType }) : null }
}
