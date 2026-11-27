from datetime import datetime, timezone

from app.core.schemas import ApiModel


class _Sample(ApiModel):
    started_at: datetime
    title: str


def test_naive_datetime_is_serialized_as_utc():
    data = _Sample(started_at=datetime(2026, 11, 27, 14, 56, 23), title="x").model_dump(mode="json", by_alias=True)
    assert data["startedAt"] == "2026-11-27T14:56:23Z"
    assert data["title"] == "x"


def test_aware_datetime_keeps_its_offset():
    value = datetime(2026, 11, 27, 22, 0, tzinfo=timezone.utc)
    assert _Sample(started_at=value, title="x").model_dump(mode="json")["started_at"].startswith("2026-11-27T22:00:00")
