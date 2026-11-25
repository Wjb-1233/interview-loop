"""Coverage means a required question actually appeared, independent of turn count."""
import re
from difflib import SequenceMatcher


def normalized_question(text: str) -> str:
    text = re.sub(r"[（(]考察[：:].*?[）)]", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text).casefold()


def covered_question_indexes(bank: list[dict], questions: list[str]) -> list[int]:
    targets = [normalized_question(item.get("text", "")) for item in bank]
    covered = set()
    for raw in questions:
        question = normalized_question(raw)
        if not question:
            continue
        # One focused question must not tick several similar required questions.
        exact = next((i for i, target in enumerate(targets) if target and target == question), None)
        if exact is not None:
            covered.add(exact)
            continue
        candidates = [(i, 1.0 if len(target) >= 8 and target in question
                       else SequenceMatcher(None, target, question).ratio())
                      for i, target in enumerate(targets) if target]
        if candidates:
            index, similarity = max(candidates, key=lambda item: item[1])
            if similarity >= 0.9:
                covered.add(index)
    return sorted(covered)


def dialogue_questions(messages) -> list[str]:
    return [message.content for message in messages if message.speaker == "AI"
            and getattr(message, "kind", None) != "CONTROL"
            and not message.content.startswith("当然，我再说一遍：")]
