import type { TrainingDelivery } from './contracts/trainingMetadata'

export interface ApiEnvelope<T> {
  data: T
  meta: { timestamp: string }
}

export interface User {
  createdAt?: string
  id: string
  email: string
  displayName: string
  role: 'STUDENT' | 'ADMIN'
  bio: string | null
  avatar: string | null
  emailVerified?: boolean
}

export interface Scene {
  id: string
  category: string
  title: string
  industry: string
  position: string
  roleName: string
  difficulty: string
  background: string
  goal: string
  tags: string[]
  openingLine: string
  competency?: string | null
  questionBank?: Array<{ text?: string; dimension?: string | null } | string>
  mine?: boolean
  source?: string
  visibility?: string
  favorite: boolean
}

export interface TrainingMessage {
  id: string
  roundNo: number
  speaker: 'USER' | 'AI'
  content: string
  flagged: boolean
  flags: readonly string[]
  createdAt: string
}

export interface TrainingSession {
  assessmentContext?: { purpose?: 'PRACTICE' | 'TRANSFER'; adaptiveEnabled?: boolean; hintUses?: number } | null
  answerTurns?: Array<{ roundNo: number; questionMessageId: string; answerMessageId: string; question: string; answer: string; flags: readonly string[] }>
  id: string
  planId?: string | null
  taskKey?: string | null
  depth?: string
  sceneId: string
  sceneTitle: string
  status: string
  stage: string
  currentRound: number
  maxRounds: number
  channel?: 'TEXT' | 'VOICE' | 'VIDEO'
  mode?: 'STANDARD' | 'DRILL'
  recordingUrl?: string | null
  durationSeconds?: number | null
  delivery?: TrainingDelivery | null
  startedAt: string
  finishedAt: string | null
  resumeFilename: string | null
  resumeOpeningDegraded: boolean
  questionPlan: Array<{ text: string; dimension: string | null; difficulty: string | null }>
  questionTotal: number
  questionCovered: number
  jdText: string | null
  jobMatch?: {
    score: number
    strengths: string[]
    gaps: Array<{ requirement: string; why: string; drill: string }>
    followUps: string[]
    degraded: boolean
    requirementCount: number
  } | null
  messages: TrainingMessage[]
}

export interface Scores {
  logic: number
  relevance: number
  correctness: number
  concision: number
}

export type ScoreDimension = keyof Scores

export interface AbilityAttempt {
  id: string
  answer: string
  score: number
  answerQuote: string
  strength: string
  gap: string
  nextAction: string
  createdAt: string
}

export interface AbilityPractice {
  evaluationId: string
  sessionId: string
  sceneId: string
  sceneTitle: string
  roundCount: number
  overallScore: number
  reportSummary: string
  dimension: ScoreDimension
  dimensionLabel: string
  baselineScore: number
  reportDegraded: boolean
  question: string
  originalAnswer: string
  evidenceQuote: string | null
  evidenceReason: string | null
  targetAction: string
  reviewTurns: Array<{
    roundNo: number
    question: string
    answer: string
    flags: string[]
    isFocusEvidence: boolean
  }>
  reportSuggestions: Array<{ roundNo: number; problem: string; original: string; rewrite: string }>
  attempts: AbilityAttempt[]
}

export interface ScriptVersion {
  id: string
  sceneId: string | null
  createdAt: string | null
  style: string
  original: string | null
  content: string
  highlights: string[]
  favorite: boolean
}

export interface MistakeItem {
  sessionId: string
  sceneId: string | null
  sceneTitle: string
  dimension: string
  score: number
  roundNo: number
  question: string
  quote: string
  reason: string
  nextAction: string
  status: 'PENDING' | 'RESOLVED'
  canResolve: boolean
  generatedCount: number
  practiceSceneId: string | null
  createdAt: string
}

export interface MessageRewrite {
  roundNo: number
  original: string
  rewrite: string
  reason: string
  flags: readonly string[]
  degraded: boolean
}

export interface Evaluation {
  assessment?: import('./contracts/interviewAssessment').InterviewAssessment | null
  qualityStatus?: 'VERIFIED' | 'PENDING_RESCORE' | 'INSUFFICIENT_EVIDENCE' | 'RULE_BASED' | 'LIMITED_SAMPLE' | 'REVIEW_REQUIRED'
  answeredRounds?: number
  missingEvidenceDimensions?: Array<keyof Scores>
  eligibleForGrowth?: boolean
  revision?: number
  revisionHistory?: Array<{ revision: number; createdAt: string; overallScore: number; summary: string; evidence: ScoreEvidence[] }>
  questionTypes?: Array<{ roundNo: number; type: 'EXPERIENCE' | 'KNOWLEDGE' | 'SOLUTION' | 'MOTIVATION' }>
  id: string
  sessionId: string
  scores: Scores
  overallScore: number | null
  scoreUnavailableReason?: string | null
  riskFlags?: string[]
  summary: string
  suggestions: Array<{ roundNo: number; problem: string; original: string; rewrite: string; reference?: string }>
  styleTags: string[]
  createdAt: string
  degraded: boolean
  reference?: string | null
  upgrades?: Array<{ original: string; problem: string; improved: string; type: string }>
  stability?: { samples: number; maxSpread: number; reliable: boolean } | null
  evidence: ScoreEvidence[]
  planId: string | null
  technicalChecks?: Array<{ roundNo: number; quote: string; verdict: string; reason: string }>
  previousScores: Scores | null
  previousOverall: number | null
  speechStats: {
    totalChars: number
    rounds: number
    fillerTotal: number
    fillerRate: number
    avgSentenceLength: number
    avgRoundLength: number
    topFillers: Array<{ word: string; count: number }>
  } | null
}

export interface ScoreEvidence {
  dimension: keyof Scores
  roundNo: number
  questionMessageId: string
  answerMessageId: string
  question: string
  answer: string
  quote: string
  reason: string
  nextAction: string
  resumeQuote: string | null
}

export interface Course {
  id: string
  title: string
  dimension: string
  minutes: number
  description: string
  content: string
  progress: number
  completed: boolean
}

export interface AdminUserRecord {
  id: string
  email: string
  displayName: string
  role: 'STUDENT' | 'ADMIN'
  active: boolean
  bio: string | null
  createdAt: string
}

export interface QuestionItem {
  text: string
  dimension: string | null
  difficulty: string | null
  rubric?: import('./contracts/interviewAssessment').QuestionRubric | null
}

export interface AdminSceneRecord extends Omit<Scene, 'favorite'> {
  active: boolean
  coreIdea?: string
  questionBank: QuestionItem[]
  sessionCount?: number
  coveredSessionCount?: number
}

export interface AdminCourseRecord extends Course { active: boolean }

export interface AdminLearnerRow {
  userId: string
  name: string
  email: string
  active: boolean
  sessions: number
  finished: number
  averageScore: number | null
  lastTrainedAt: string | null
}

export interface AdminSessionRecord {
  id: string
  userId: string
  sceneTitle: string
  userName: string
  email: string
  status: string
  rounds: number
  startedAt: string
  overallScore: number | null
}

export type PlanTaskAction = 'COURSE' | 'TRAINING' | 'REWRITE' | 'RETEST' | 'SCENE' | 'REVIEW' | 'VIDEO' | 'VOICE' | 'REPORT'

export interface PersonalizedLesson {
  title: string
  intro: string
  steps: ReadonlyArray<{ title: string; explanation: string; example: string }>
  exercise: string
  aiGenerated: boolean
}

export interface LessonResponse {
  lesson: PersonalizedLesson
  source: { title: string; description: string; content: string }
}

export interface LessonVideoChapter {
  title: string
  start: number
  duration: number
}

/** 微课视频生成进度（GET/POST /training-plans/{id}/lesson/video[/state]） */
export interface LessonVideoState {
  jobId?: string | null
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  progress: number
  stage?: string | null
  url?: string | null
  chapters?: ReadonlyArray<LessonVideoChapter>
  error?: string | null
}

export interface TrainingPlanTask {
  key: string
  day: number
  task: string
  actionType: PlanTaskAction
  dimension?: string | null
  completed: boolean
  completedAt: string | null
  evidence: string | null
  courseId: string | null
  sceneId: string | null
  sourceSessionId: string | null
  lesson: PersonalizedLesson | null
  completedSteps: readonly number[]
  learningProgress: number
  practiceAnswer: string | null
  practiceFeedback: string | null
  practicePassed: boolean
  practiceDegraded: boolean
  channel?: string
  depth?: string
  learned?: boolean
  rewriteFeedback: string | null
  rewritePassed: boolean
  rewriteDegraded: boolean
}

export interface ScoreComparison {
  baselineSessionId: string
  retestSessionId: string
  sceneId: string
  baselineScores: Scores
  retestScores: Scores
  scoreDeltas: Record<keyof Scores, number>
  baselineOverall: number
  retestOverall: number
  overallDelta: number
  focusDelta: number
  status: 'IMPROVED' | 'NEEDS_PRACTICE' | 'PROVISIONAL'
  recommendation: string
}

export interface TrainingPlan {
  transfer?: import('./contracts/interviewAssessment').TransferOverview | null
  sequence: number
  id: string
  title: string
  focusDimension: string
  status: 'ACTIVE' | 'COMPLETED' | 'SUPERSEDED' | 'ARCHIVED'
  progress: number
  tasks: readonly TrainingPlanTask[]
  comparison: ScoreComparison | null
  createdAt: string
}

