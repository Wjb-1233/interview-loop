"""Project editable media transcripts from the same canonical pairs as scoring."""
from app.features.training.answer_turns import answer_turns


def transcript_delivery(delivery, messages, channel: str) -> dict | None:
    if channel not in {"VOICE", "VIDEO"}:
        return delivery
    result = dict(delivery or {})
    saved = {item.get("roundNo"): item for item in result.get("transcript", []) if isinstance(item, dict)}
    result["transcript"] = [
        {**saved.get(turn.round_no, {}), "roundNo": turn.round_no,
         "question": turn.question.content, "text": turn.answer.content,
         "questionMessageId": turn.question.id, "answerMessageId": turn.answer.id,
         "startMs": saved.get(turn.round_no, {}).get("startMs"),
         "endMs": saved.get(turn.round_no, {}).get("endMs"),
         "confidence": saved.get(turn.round_no, {}).get("confidence"),
         "edited": bool(saved.get(turn.round_no, {}).get("edited", False))}
        for turn in answer_turns(messages, channel)
    ]
    return result
