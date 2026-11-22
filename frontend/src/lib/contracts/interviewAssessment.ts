export interface InterviewAssessment {
  version: string
  rubricVersion?: string
  model?: string
  purpose: 'PRACTICE' | 'TRANSFER'
  hintUses: number
  consistencyConflicts: Array<{ roundNo: number; quote: string; reason: string }>
  professionalMatrix: Array<{
    competencyId: string; name: string
    status: 'NOT_COVERED' | 'LIMITED' | 'UNCERTAIN' | 'DEMONSTRATED'
    expectedPoints: string[]; metPoints: string[]; missingPoints: string[]
    evidence: Array<{ roundNo: number; quote: string; answerMessageId: string }>
    reason: string; rubricVersion: string; reviewed: boolean; referenceUrl?: string | null
  }>
  evidenceTrace: Array<{
    roundNo: number; competency: string; question: string; nextQuestion: string; decisionReason: string
    missingPoints: string[]; observations: Array<{ point: string; quote: string; level: string }>; degraded: boolean
  }>
  transfer?: { result: 'INSUFFICIENT_SAMPLE' | 'AWAITING_REVIEW' | 'INDEPENDENT_APPLICATION' | 'NEEDS_PRACTICE'; answeredRounds: number; note: string; planId: string } | null
}

export interface TransferOverview {
  available: boolean; reason: string
  attempts: ReadonlyArray<{ sessionId: string; status: string; createdAt: string; result: string | null }>
}

export interface QuestionRubric {
  competency: string; version: string; requiredPoints: string[]; acceptableVariants: string[]
  commonMistakes: string[]; referenceUrl: string | null; reviewed: boolean; transferQuestions: string[]
}
