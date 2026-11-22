import type { QuestionRubric } from './contracts/interviewAssessment'

export function importedRubric(value: unknown): QuestionRubric | null {
  if (value === undefined || value === null) return null
  if (typeof value !== 'object' || !('competency' in value) || typeof value.competency !== 'string') throw new Error('考察标准需要 competency 名称。')
  const row = value as Record<string, unknown>
  const list = (key: string): string[] => {
    const items = row[key] ?? []
    if (!Array.isArray(items) || items.some(item => typeof item !== 'string')) throw new Error(`${key} 需要文字数组。`)
    return items as string[]
  }
  return { competency: value.competency, version: typeof row.version === 'string' ? row.version : 'v1',
    requiredPoints: list('requiredPoints'), acceptableVariants: list('acceptableVariants'), commonMistakes: list('commonMistakes'),
    transferQuestions: list('transferQuestions'), referenceUrl: typeof row.referenceUrl === 'string' ? row.referenceUrl : null,
    reviewed: row.reviewed === true }
}
