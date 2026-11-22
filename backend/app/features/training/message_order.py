"""文字回复与录音转写的轮次含义不同，按业务顺序排列问答。"""
from sqlalchemy import and_, case, exists, or_, select
from sqlalchemy.orm import aliased

from app.db.models import Message


def dialogue_order(channel: str):
    # 文字：开场 AI(0)，回答 USER(n)，随后追问 AI(n)。
    # 语音/视频：一轮中先保存问题 AI(n)，再保存回答 USER(n)。
    first_speaker = 'USER' if channel == 'TEXT' else 'AI'
    return (Message.round_no, case((Message.speaker == first_speaker, 0), else_=1), Message.created_at, Message.id)


def first_message_in_round(message):
    """SQL predicate for the first same-speaker message in dialogue_order()."""
    earlier = aliased(Message)
    return and_(message.kind != "CONTROL", ~exists(select(1).where(
        earlier.kind != "CONTROL",
        earlier.session_id == message.session_id,
        earlier.speaker == message.speaker,
        earlier.round_no == message.round_no,
        or_(earlier.created_at < message.created_at,
            and_(earlier.created_at == message.created_at, earlier.id < message.id)),
    ).correlate(message)))
