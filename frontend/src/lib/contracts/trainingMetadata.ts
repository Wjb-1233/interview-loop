/** Saved observations are sparse: a prepared/text attempt has no audio metrics. */
export interface AudioDeliveryMetrics {
  speechRate?: number
  articulationRate?: number
  pauseCount?: number
  longestPause?: number
  durationSeconds?: number
  charCount?: number
  fillerTotal?: number
}

export interface CameraObservations {
  available?: boolean
  faceRatio?: number
  eyeContactRatio?: number
  headStability?: number
  brightness?: number
  centerOffset?: number
  framing?: number
  onCamera?: number
  stability?: number
  lighting?: number
  tips?: string[]
}

export interface TrainingDelivery extends AudioDeliveryMetrics {
  plannedDurationMinutes?: number
  engine?: string
  vision?: CameraObservations | null
  marks?: Array<{ text: string; start: number; end?: number }>
  selfReview?: Array<{ roundNo: number; camera: boolean; structure: boolean; opening: boolean; note: string | null }>
  transcript?: Array<{ roundNo: number; question: string; text: string; startMs: number | null; endMs: number | null; confidence: number | null; edited: boolean }>
  rescoreRequired?: boolean
  pendingEvaluationSnapshot?: unknown
  segments?: Array<{ roundNo: number; question: string; startMs: number; endMs: number; file: string; url: string | null }>
}
