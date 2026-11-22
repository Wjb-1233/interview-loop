import type { TrainingMessage, TrainingSession } from './types'

/** Prefer the server's canonical projection; fallback supports older servers/mocks. */
export function reportAnswerTurns(session: TrainingSession | null, messages: TrainingMessage[]) {
  const canonical = new Map(session?.answerTurns?.map(turn => [turn.answerMessageId, turn]) ?? [])
  const questions = new Map<number, TrainingMessage>()
  const answers = new Map<number, TrainingMessage>()
  for (const message of messages) {
    const target = message.speaker === 'AI' ? questions : message.speaker === 'USER' ? answers : null
    if (target && !target.has(message.roundNo)) target.set(message.roundNo, message)
  }
  const offset = session?.channel === 'TEXT' || !session?.channel ? 1 : 0
  return [...answers.values()].filter(answer => answer.roundNo >= 1).sort((a,b) => a.roundNo-b.roundNo).map(answer => canonical.get(answer.id) ?? ({
    roundNo: answer.roundNo,
    questionMessageId: questions.get(answer.roundNo-offset)?.id ?? '', answerMessageId: answer.id,
    question: questions.get(answer.roundNo-offset)?.content ?? '', answer: answer.content, flags: answer.flags,
  }))
}
