"""Pair by answer round; the first message in dialogue_order wins duplicates."""
from dataclasses import dataclass
from app.db.models import Message
from app.features.training.language import is_repeat_request


@dataclass(frozen=True)
class AnswerTurn:
    round_no: int
    question: Message
    answer: Message


def question_round(answer_round: int, channel: str) -> int:
    return answer_round - question_offset(channel)


def question_offset(channel: str) -> int:
    return 1 if channel == "TEXT" else 0


def answer_turns(messages, channel: str) -> list[AnswerTurn]:
    questions = {}
    for message in messages:
        if message.speaker == "AI" and getattr(message, "kind", None) != "CONTROL" and not message.content.startswith("当然，我再说一遍："):
            questions.setdefault(message.round_no, message)
    turns = {}
    for answer in messages:
        if answer.speaker != "USER" or answer.round_no < 1 or getattr(answer, "kind", None) == "CONTROL" or is_repeat_request(answer.content):
            continue
        question = questions.get(question_round(answer.round_no, channel))
        if question is not None:
            # Non-counting "repeat the question" messages must not replace an answer.
            turns.setdefault(answer.round_no, AnswerTurn(answer.round_no, question, answer))
    return [turns[number] for number in sorted(turns)]
