from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, field_serializer


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    @field_serializer("*", mode="wrap")
    def _datetime_as_utc(self, value: Any, handler: SerializerFunctionWrapHandler) -> Any:
        # MySQL / SQLite 读回的 datetime 不带时区；库内一律存 UTC，输出时补上 +00:00，
        # 否则浏览器会按本地时区解析（东八区整场计时会多出 480 分钟）。
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return handler(value)
