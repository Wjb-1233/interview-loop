from datetime import datetime

from pydantic import Field

from app.core.schemas import ApiModel
from app.features.evaluations.status import ReportQualityStatus


class DimensionScores(ApiModel):
    """四维评分：内容与逻辑 / 贴合问题 / 信息完整 / 表达干净。

    appropriateness 仅为兼容历史数据保留，新评分不再单独打分。
    """

    logic: int = Field(ge=1, le=5, description="内容与逻辑")
    relevance: int = Field(ge=1, le=5, description="贴合问题")
    correctness: int = Field(ge=1, le=5, description="信息完整度；历史字段名保留，专业事实核查另见 technicalChecks")
    concision: int = Field(ge=1, le=5, description="表达干净与清晰程度，不是越短越好")
    appropriateness: int = Field(default=3, ge=1, le=5, exclude=True)


class EvaluationPayload(ApiModel):
    scores: DimensionScores
    summary: str
    suggestions: list[dict]
    style_tags: list[str]
    evidence: list[dict] = Field(default_factory=list)
    technical_checks: list[dict] = Field(default_factory=list)
    professional_matrix: list[dict] = Field(default_factory=list, max_length=20)
    reference: str = ""
    risk: list[str] = Field(default_factory=list)
    upgrades: list[dict] = Field(default_factory=list)


class EvidenceDraft(ApiModel):
    dimension: str
    round_no: int = Field(ge=1, le=12)
    quote: str = Field(min_length=4, max_length=240)
    reason: str = Field(min_length=4, max_length=500)
    next_action: str = Field(min_length=4, max_length=300)
    resume_quote: str | None = Field(default=None, max_length=240)


class EvidenceView(ApiModel):
    dimension: str
    round_no: int
    question_message_id: str
    answer_message_id: str
    question: str
    answer: str
    quote: str
    reason: str
    next_action: str
    resume_quote: str | None = None


class EvaluationView(ApiModel):
    id: str
    session_id: str
    scores: DimensionScores
    # 专业核查与四维评分矛盾且未消解时，读接口不给数字，只在库里保留原值。
    overall_score: float | None = None
    score_unavailable_reason: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    summary: str
    suggestions: list[dict]
    style_tags: list[str]
    created_at: datetime
    degraded: bool = False
    quality_status: ReportQualityStatus = ReportQualityStatus.INSUFFICIENT_EVIDENCE
    missing_evidence_dimensions: list[str] = Field(default_factory=list)
    eligible_for_growth: bool = False
    answered_rounds: int = 0
    revision: int = 1
    revision_history: list[dict] = Field(default_factory=list)
    evidence: list[EvidenceView] = Field(default_factory=list)
    plan_id: str | None = None
    speech_stats: dict | None = None
    reference: str | None = None
    stability: dict | None = None
    assessment: dict | None = None
    upgrades: list[dict] = Field(default_factory=list)
    technical_checks: list[dict] = Field(default_factory=list)
    previous_scores: DimensionScores | None = None
    question_types: list[dict] = Field(default_factory=list)
    previous_overall: float | None = None

