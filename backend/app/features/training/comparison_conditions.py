"""Shared comparison conditions for reports and the growth dashboard."""
from app.db.models import ResumeContext, TrainingSession
from sqlalchemy import func

CONDITION_FIELDS = ('scene_id', 'channel', 'depth', 'mode', 'language', 'jd_text')


def condition_filters(training: TrainingSession, resume_text: str | None) -> list:
    version = (training.assessment_context or {}).get('rubricVersion', 'legacy')
    return [*(getattr(TrainingSession, key) == getattr(training, key) for key in CONDITION_FIELDS), ResumeContext.content == resume_text,
            func.coalesce(TrainingSession.assessment_context['rubricVersion'].as_string(), 'legacy') == version]
