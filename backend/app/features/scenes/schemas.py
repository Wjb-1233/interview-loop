from typing import Annotated
from pydantic import Field, field_validator

from app.core.schemas import ApiModel


class QuestionRubric(ApiModel):
    competency: str = Field(min_length=2, max_length=60)
    version: str = Field(default="v1", min_length=1, max_length=40)
    required_points: list[Annotated[str, Field(min_length=2, max_length=200)]] = Field(min_length=1, max_length=8)
    acceptable_variants: list[Annotated[str, Field(min_length=2, max_length=200)]] = Field(default_factory=list, max_length=8)
    common_mistakes: list[Annotated[str, Field(min_length=2, max_length=200)]] = Field(default_factory=list, max_length=8)
    reference_url: str | None = Field(default=None, max_length=500)
    reviewed: bool = False
    transfer_questions: list[Annotated[str, Field(min_length=5, max_length=300)]] = Field(default_factory=list, max_length=4)

    @field_validator("reference_url")
    @classmethod
    def safe_reference(cls, value):
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("参考资料网址必须使用 http 或 https")
        return value


class QuestionItem(ApiModel):
    text: str = Field(min_length=2, max_length=300)
    dimension: str | None = Field(default=None, max_length=20)
    difficulty: str | None = Field(default=None, max_length=20)
    rubric: QuestionRubric | None = None


class SceneView(ApiModel):
    id: str
    category: str
    title: str
    industry: str
    position: str
    role_name: str
    difficulty: str
    background: str
    goal: str
    tags: list[str]
    opening_line: str
    competency: str | None = None
    question_bank: list = Field(default_factory=list)
    source: str = 'builtin'
    visibility: str = 'public'
    mine: bool = False
    favorite: bool = False


class MyScenePayload(ApiModel):
    title: str = Field(min_length=4, max_length=60)
    industry: str = Field(min_length=2, max_length=30)
    position: str = Field(min_length=2, max_length=40)
    role_name: str = Field(min_length=2, max_length=30)
    category: str = Field(default="自定义", max_length=30)
    difficulty: str = Field(default="中级", max_length=10)
    background: str = Field(default="", max_length=500)
    goal: str = Field(default="", max_length=300)
    opening_line: str = Field(default="", max_length=200)
    competency: str | None = Field(default=None, max_length=30)
    tags: list[str] = Field(default_factory=list, max_length=6)
    questions: list[dict] = Field(default_factory=list, min_length=1, max_length=8)


class JdDraftRequest(ApiModel):
    jd: str = Field(min_length=1, max_length=4000)
    position: str = Field(default="", max_length=40)
    category: str = Field(default="自定义", max_length=30)
    difficulty: str = Field(default="中级", max_length=10)
