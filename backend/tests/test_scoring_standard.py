from types import SimpleNamespace

from app.features.evaluations import scoring
from app.features.evaluations.standards import current_standard, scoring_prompt, standard_metadata
from app.features.training.rubrics import fresh_context, new_context


def test_new_attempt_freezes_actual_scoring_prompt_and_comparison_version(monkeypatch):
    scene = SimpleNamespace(category='技术一面', position='Python 后端开发')
    old = new_context(scene, [], True)
    frozen = old['scoringStandard']
    monkeypatch.setattr(scoring, 'SYSTEM_PROMPT', scoring.SYSTEM_PROMPT + '\n新的校准要求')
    new = new_context(scene, [], True)
    assert scoring_prompt(old) == frozen['systemPrompt']
    assert new['rubricVersion'] != old['rubricVersion']
    assert fresh_context(old)['scoringStandard'] == frozen
    assert standard_metadata(old)['hash'] == frozen['hash']
    assert 'systemPrompt' not in standard_metadata(old)


def test_legacy_context_is_not_relabelled_as_calibrated():
    assert standard_metadata(None)['id'] == 'legacy-unversioned'
    assert scoring_prompt(None) == scoring.SYSTEM_PROMPT
    standard = current_standard()
    assert standard['humanCalibration'] == 'PENDING'
    assert len(standard['dimensions']) == 4
    assert '不得把参与' in standard['systemPrompt']
