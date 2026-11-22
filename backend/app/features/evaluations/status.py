"""Report quality is distinct from model availability and training lifecycle."""
from enum import Enum


class ReportQualityStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PENDING_RESCORE = "PENDING_RESCORE"
    RULE_BASED = "RULE_BASED"
    LIMITED_SAMPLE = "LIMITED_SAMPLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
