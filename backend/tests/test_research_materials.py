"""Only synthetic fixtures; these tests are not participant experiment results."""
import json
from types import SimpleNamespace

import pytest

from app.features.evaluations.agreement import weighted_kappa
from app.features.evaluations.research import prepare_calibration, analyze_calibration, read_csv, write_csv, ordinal
from app.features.evaluations.study import prepare_study, blind_study, analyze_study
from app.features.training.rubrics import new_context
from app.features.plans.transfer import candidate_questions


def test_calibration_is_blind_blank_and_question_split(tmp_path):
    pack = tmp_path / 'calibration'
    manifest = prepare_calibration(pack)
    assert manifest['sampleCount'] == 48 and manifest['developmentCases'] == manifest['holdoutCases'] == 24
    a, b = read_csv(pack / 'rater_a.csv'), read_csv(pack / 'rater_b.csv')
    assert len(a) == len(b) == 192 and a != b
    assert all(not row['human_score'] for row in a + b)
    assert set(a[0]) == {'sample_id', 'dimension', 'conversation', 'human_score', 'note'}
    key = read_csv(pack / 'private/key.csv')
    families = [{row['family_id'] for row in key if row['split'] == split} for split in ('development', 'holdout')]
    assert not families[0] & families[1]
    result = analyze_calibration(pack)
    assert result['status'] == 'AWAITING_HUMAN_LABELS' and result['perDimension'] == {}
    assert result['modelComparison'] is None
    with pytest.raises(FileExistsError):
        prepare_calibration(pack)


@pytest.mark.parametrize('value', ['0', '6', '3.5', 'NaN', 'inf', 'bad'])
def test_invalid_human_labels_rejected(value):
    with pytest.raises(ValueError):
        ordinal(value, 'sample')


@pytest.mark.parametrize('mutation', ['text', 'missing', 'duplicate', 'extra'])
def test_calibration_pairing_tampering_rejected(tmp_path, mutation):
    pack = tmp_path / 'calibration'
    prepare_calibration(pack)
    rows = read_csv(pack / 'rater_a.csv')
    if mutation == 'text':
        rows[0]['conversation'] += 'edited'
    elif mutation == 'missing':
        rows.pop()
    elif mutation == 'duplicate':
        rows.append(rows[0])
    else:
        rows.append(dict(rows[0], sample_id='unknown'))
    write_csv(pack / 'rater_a.csv', rows)
    with pytest.raises(ValueError):
        analyze_calibration(pack)


def test_calibration_computes_separate_raters_and_rejects_stale_model(tmp_path):
    pack = tmp_path / 'calibration'
    prepare_calibration(pack)
    for rater in ('a', 'b'):
        rows = read_csv(pack / f'rater_{rater}.csv')
        for index, row in enumerate(sorted(rows, key=lambda row: row['sample_id'])):
            row['human_score'] = index % 5 + 1
        write_csv(pack / f'rater_{rater}.csv', rows)
    (pack / 'raters.json').write_text(json.dumps({'raterA': 'test-rater-A', 'raterB': 'test-rater-B'}))
    result = analyze_calibration(pack)
    assert all(stats['exactAgreement'] == 1 for stats in result['perDimension'].values())
    model = [dict(row, model_score=3, standard_hash='wrong') for row in read_csv(pack / 'private/key.csv')]
    write_csv(pack / 'private/model.csv', model)
    with pytest.raises(ValueError, match='版本'):
        analyze_calibration(pack, model_path=pack / 'private/model.csv')


def test_linear_weighted_kappa_handles_chance_and_constants():
    assert weighted_kappa([(1, 1), (5, 5)]) == 1
    assert weighted_kappa([(1, 5), (5, 1)]) == -1
    assert weighted_kappa([(1, 1), (1, 5), (5, 1), (5, 5)]) == 0
    assert weighted_kappa([(3, 3), (3, 3)]) is None


def test_default_transfer_specs_filter_difficulty_preserve_custom_and_legacy():
    scene = SimpleNamespace(category='技术一面', position='Python 后端开发')
    context = new_context(scene, [])
    for difficulty in ('入门', '中级', '进阶'):
        candidates = candidate_questions(context, difficulty)
        assert len(candidates) == 12
        for criterion, question in candidates:
            spec = next(item for item in criterion['transferQuestionSpecs'] if item['text'] == question)
            assert spec['difficulty'] == difficulty and spec['equivalenceValidated'] is False
    assert candidate_questions({'criteria': [{'id': 'custom', 'transferQuestions': ['我的迁移题']}]}, '中级')[0][1] == '我的迁移题'
    assert len(candidate_questions({'criteria': [{'id': 'transaction'}]}, '中级')) == 3


def test_empty_study_never_claims_effect(tmp_path):
    pack = tmp_path / 'study'
    prepare_study(pack, 4)
    result = analyze_study(pack)
    assert result['status'] == 'AWAITING_PARTICIPANTS' and result['outcomes'] is None
    with pytest.raises(ValueError):
        blind_study(pack, tmp_path / 'blind')


def complete_synthetic_study(pack):
    prepare_study(pack, 4)
    manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    participants = read_csv(pack / 'participants.csv')
    for row in participants:
        row.update(consent='YES', disposition='COMPLETE', training_minutes='15', training_notes='SYNTHETIC UNIT TEST ONLY')
        for phase in ('pre', 'post', 'transfer'):
            row.update({f'{phase}_session_id': f"synthetic-{row['participant_id']}-{phase}",
                        f'{phase}_channel': 'TEXT', f'{phase}_difficulty': '中级',
                        f'{phase}_depth': 'STANDARD', f'{phase}_standard_hash': manifest['standardHash']})
    write_csv(pack / 'participants.csv', participants)
    observations = read_csv(pack / 'observations.csv')
    for row in observations:
        row['answer'] = '仅限单元测试的合成回答，不是真人数据。'
    write_csv(pack / 'observations.csv', observations)


def test_study_analysis_pairs_people_not_dimension_rows(tmp_path):
    pack, blind = tmp_path / 'study', tmp_path / 'blind'
    complete_synthetic_study(pack)
    assert blind_study(pack, blind)['rowsPerRater'] == 192
    assert analyze_study(pack, blind)['outcomes'] is None
    (blind / 'raters.json').write_text(json.dumps({'raterA': 'test-rater-A', 'raterB': 'test-rater-B'}))
    # Same score everywhere => zero change, despite 384 dimension ratings.
    for rater in ('a', 'b'):
        rows = read_csv(blind / f'rater_{rater}.csv')
        for row in rows:
            row['human_score'] = 3
        write_csv(blind / f'rater_{rater}.csv', rows)
    result = analyze_study(pack, blind)
    assert result['completeParticipants'] == 4
    assert result['outcomes']['meanChange'] == 0
    assert result['outcomes']['participantBootstrapMeanChange95CI'] == [0, 0]
    rows[0]['conversation'] += 'forged'
    write_csv(blind / 'rater_b.csv', rows)
    with pytest.raises(ValueError, match='正文'):
        analyze_study(pack, blind)


@pytest.mark.parametrize('fault', ['consent', 'same-session', 'conditions'])
def test_study_rejects_unconsented_or_unpaired_sessions(tmp_path, fault):
    pack = tmp_path / 'study'
    complete_synthetic_study(pack)
    people = read_csv(pack / 'participants.csv')
    if fault == 'consent':
        people[0]['consent'] = ''
    elif fault == 'same-session':
        people[0]['post_session_id'] = people[0]['pre_session_id']
    else:
        people[0]['post_channel'] = 'VOICE'
    write_csv(pack / 'participants.csv', people)
    with pytest.raises(ValueError):
        analyze_study(pack)
