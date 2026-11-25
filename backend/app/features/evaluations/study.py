"""Small single-arm pre/post/transfer study. Planned slots are never observations."""
import hashlib
import json
import random
from pathlib import Path
from statistics import fmean, median

from app.features.evaluations.research import write_csv, read_csv, indexed, load_rater, RATER_FIELDS, require_independent_raters
from app.features.evaluations.standards import current_standard, DIMENSION_LABELS

FORMS = {
    'A': [
        ('project', '请说明一次你亲自完成的接口改动，区分团队贡献，解释选择与验证。'),
        ('transaction', '一次请求要同时更新订单和余额，你如何保持业务约束并验证失败处理？'),
        ('cache', '文章更新后读者仍看到旧缓存，如何明确允许延迟并设计更新与失败处理？'),
        ('diagnosis', '某查询接口从今天开始变慢，如何确认范围、定位、止损并验证修复？')],
    'B': [
        ('project', '请说明一次你亲自参与的性能优化，区分本人职责，解释方案取舍与验证。'),
        ('transaction', '退款需要同时更新退款单和账户余额，你如何保持约束并验证失败重试？'),
        ('cache', '课程信息调整后用户仍读到旧内容，如何明确一致性要求并处理失效失败？'),
        ('diagnosis', '发布后部分接口超时增加，如何核实范围、收集证据、止损并验证？')],
    'C': [
        ('project', '你负责消息任务的重试模块，同伴负责主流程，如何解释贡献、取舍和验证边界？'),
        ('transaction', '两个终端同时核销一张兑换码，如何约束数据、处理重试并验证结果？'),
        ('cache', '门店营业状态允许短暂延迟，但预约前必须确认，如何设计并验证缓存边界？'),
        ('diagnosis', '只有某一批文件的导出耗时上升，如何确定范围、定位、止损并验证？')],
}
PHASES = ('pre', 'post', 'transfer')
CONDITIONS = ('channel', 'difficulty', 'depth', 'standard_hash')


def dump(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare_study(directory: Path, slots: int = 12) -> dict:
    if not 4 <= slots <= 40 or slots % 2:
        raise ValueError('计划人数须为 4–40 的偶数，以平衡 AB/BA；这不是已招募人数')
    directory.mkdir(parents=True, exist_ok=False)
    standard = current_standard()
    dump(directory / 'standard.json', standard)
    participants, observations = [], []
    for number in range(1, slots + 1):
        identity = f'P{number:02}'
        sequence = 'AB' if number % 2 else 'BA'
        participant = {'participant_id': identity, 'sequence': sequence, 'consent': '', 'disposition': '',
                       'training_minutes': '', 'training_notes': ''}
        for phase in PHASES:
            participant[f'{phase}_session_id'] = ''
            for field in CONDITIONS:
                participant[f'{phase}_{field}'] = ''
            form = sequence[0 if phase == 'pre' else 1] if phase != 'transfer' else 'C'
            for competency, question in FORMS[form]:
                observations.append({'sample_id': f'{identity}-{phase}-{competency}',
                    'participant_id': identity, 'phase': phase, 'form': form,
                    'competency_id': competency, 'question': question, 'answer': ''})
        participants.append(participant)
    write_csv(directory / 'participants.csv', participants)
    write_csv(directory / 'observations.csv', observations)
    dump(directory / 'forms.json', {'reviewStatus': 'AUTHOR_DRAFT', 'equivalenceValidated': False, 'forms': FORMS})
    manifest = {'status': 'AWAITING_PARTICIPANTS', 'plannedSlots': slots, 'participantsCollected': 0,
                'standardHash': standard['hash'], 'design': 'SINGLE_ARM_COUNTERBALANCED_AB_BA',
                'formsHash': hashlib.sha256(json.dumps(FORMS, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                'trainingTargetMinutes': 15, 'recommendedConditions': {'channel': 'TEXT', 'difficulty': '中级', 'depth': 'STANDARD'},
                'primaryOutcome': '每位参与者后测四维均分减前测四维均分；两位独立评审均值；1–5 分',
                'secondaryOutcome': '独立迁移测均分及其相对前测的差值',
                'analysisUnit': 'participant', 'causalClaimAllowed': False,
                'source': 'EMPTY_PLANNED_SLOTS', 'equivalenceValidated': False}
    dump(directory / 'manifest.json', manifest)
    return manifest


def study_inputs(directory: Path):
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    forms = json.loads((directory / 'forms.json').read_text(encoding='utf-8'))['forms']
    if hashlib.sha256(json.dumps(forms, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != manifest['formsHash']:
        raise ValueError('题面正文与冻结版本不一致')
    standard = json.loads((directory / 'standard.json').read_text(encoding='utf-8'))
    if hashlib.sha256(standard['systemPrompt'].encode()).hexdigest() != manifest['standardHash']:
        raise ValueError('评分标准与冻结版本不一致')
    participants = indexed([dict(row, sample_id=row['participant_id']) for row in read_csv(directory / 'participants.csv')], 'participants')
    observations = indexed(read_csv(directory / 'observations.csv'), 'observations')
    expected_ids, sessions = set(), set()
    complete = []
    incomplete, excluded = [], []
    for identity, person in participants.items():
        sequence = person.get('sequence')
        if sequence not in {'AB', 'BA'}:
            raise ValueError(f'{identity}: sequence 须为 AB/BA')
        has_data = any(row.get('answer', '').strip() for row in observations.values() if row['participant_id'] == identity)
        disposition = person.get('disposition', '')
        if disposition not in {'', 'COMPLETE', 'NOT_ENROLLED', 'WITHDRAWN'}:
            raise ValueError(f'{identity}: disposition 不合法')
        exclude = disposition in {'NOT_ENROLLED', 'WITHDRAWN'}
        if exclude:
            if has_data or any(person.get(f'{phase}_session_id') for phase in PHASES):
                raise ValueError(f'{identity}: 未入组或撤回者须清空回答与会话编号，保留处置记录')
            excluded.append({'participantId': identity, 'reason': disposition})
        if person.get('consent') != 'YES':
            if has_data or any(person.get(f'{phase}_session_id') for phase in PHASES):
                raise ValueError(f'{identity}: 未记录自愿同意，不能分析或导出个人回答')
            if not exclude:
                incomplete.append(identity)
        valid = person.get('consent') == 'YES' and disposition == 'COMPLETE'
        reference = tuple(person.get(f'pre_{field}') for field in CONDITIONS)
        for phase in PHASES:
            session_id = person.get(f'{phase}_session_id', '').strip()
            if session_id:
                if session_id in sessions:
                    raise ValueError('同一 session_id 不能重复用作不同参与者或测次')
                sessions.add(session_id)
            actual = tuple(person.get(f'{phase}_{field}') for field in CONDITIONS)
            if not session_id or not all(actual):
                valid = False
            elif actual != reference or actual[-1] != manifest['standardHash']:
                raise ValueError(f'{identity}: 前后测方式、难度、深度或评分版本不一致')
            form = sequence[0 if phase == 'pre' else 1] if phase != 'transfer' else 'C'
            for competency, question in forms[form]:
                sample_id = f'{identity}-{phase}-{competency}'
                expected_ids.add(sample_id)
                row = observations.get(sample_id)
                if not row or any(row.get(key) != value for key, value in {
                    'participant_id': identity, 'phase': phase, 'form': form,
                    'competency_id': competency, 'question': question}.items()):
                    raise ValueError(f'{sample_id}: 题目、测次或配对被改动')
                if not row.get('answer', '').strip():
                    valid = False
        if valid:
            try:
                minutes = float(person['training_minutes'])
            except (ValueError, TypeError):
                raise ValueError(f'{identity}: 须填写实际训练分钟数') from None
            if not 0 < minutes <= 240:
                raise ValueError(f'{identity}: 实际训练分钟数不合理')
            complete.append(identity)
        elif identity not in incomplete and not exclude:
            incomplete.append(identity)
    if set(observations) != expected_ids or len(participants) != manifest['plannedSlots']:
        raise ValueError('计划槽位或作答集合被改动；保留未参加者并标为空白')
    return manifest, participants, observations, complete, incomplete, excluded


def study_labels(observations: dict) -> tuple[list[dict], dict]:
    labels, key = [], {}
    for raw_id, row in observations.items():
        group = hashlib.sha256(raw_id.encode()).hexdigest()[:12]
        for dimension, label in DIMENSION_LABELS.items():
            identity = group + '-' + dimension
            conversation = f"问：{row['question']}\n答：{row['answer']}" if row['answer'].strip() else ''
            labels.append(dict(sample_id=identity, dimension=label, conversation=conversation, human_score='', note=''))
            key[identity] = dict(row, dimension=label, conversation=conversation)
    return labels, key


def blind_study(directory: Path, out: Path) -> dict:
    _, _, observations, complete, incomplete, _ = study_inputs(directory)
    if incomplete or not complete:
        raise ValueError('尚有待完成槽位或没有完成者；先记录实际完成、未入组或撤回状态')
    observations = {key: row for key, row in observations.items() if row['participant_id'] in complete}
    labels, _ = study_labels(observations)
    out.mkdir(parents=True, exist_ok=False)
    dump(out / 'raters.json', {'raterA': '', 'raterB': ''})
    for rater, seed in [('a', 20261125), ('b', 20261126)]:
        shuffled = list(labels)
        random.Random(seed).shuffle(shuffled)
        write_csv(out / f'rater_{rater}.csv', shuffled, RATER_FIELDS)
    return {'status': 'AWAITING_HUMAN_LABELS', 'participants': len(complete), 'rowsPerRater': len(labels)}


def bootstrap_mean(values: list[float], seed: int = 20261125):
    if len(values) < 4:
        return None
    rng = random.Random(seed)
    draws = sorted(fmean(rng.choices(values, k=len(values))) for _ in range(2000))
    return [round(draws[50], 3), round(draws[1949], 3)]


def analyze_study(directory: Path, blind: Path | None = None) -> dict:
    manifest, _, observations, complete, incomplete, excluded = study_inputs(directory)
    result = {'status': 'AWAITING_PARTICIPANTS' if incomplete or not complete else 'AWAITING_HUMAN_LABELS',
              'plannedSlots': manifest['plannedSlots'], 'completeParticipants': len(complete),
              'incompleteParticipants': incomplete, 'outcomes': None,
              'excludedParticipants': excluded,
              'limitations': ['单组前后测没有对照组，不能证明因果关系', 'A/B/C 题目尚未真人验证等难度',
                             '用户填写数据，工具未独立核验实际参与者或会话真实性', '小样本结果仅供探索；按参与者而非维度行重采样']}
    if incomplete or not complete or blind is None:
        return result
    observations = {key: row for key, row in observations.items() if row['participant_id'] in complete}
    _, key = study_labels(observations)
    a = load_rater(blind / 'rater_a.csv', key)
    b = load_rater(blind / 'rater_b.csv', key)
    if any(value is None for value in [*a.values(), *b.values()]):
        return result
    require_independent_raters(blind)
    changes, transfers, per_person = [], [], []
    for identity in complete:
        scores = {phase: fmean((a[i] + b[i]) / 2 for i, row in key.items()
                             if row['participant_id'] == identity and row['phase'] == phase) for phase in PHASES}
        changes.append(scores['post'] - scores['pre'])
        transfers.append(scores['transfer'] - scores['pre'])
        per_person.append({'participantId': identity, **scores, 'change': changes[-1], 'transferChange': transfers[-1]})
    result.update(status='EXPLORATORY_COMPLETE', outcomes={
        'scale': '1–5；如需 100 分展示可乘 20', 'participants': per_person,
        'meanChange': round(fmean(changes), 3), 'medianChange': round(median(changes), 3),
        'improvedFraction': round(sum(value > 0 for value in changes) / len(changes), 3),
        'meanTransferChange': round(fmean(transfers), 3), 'participantBootstrapMeanChange95CI': bootstrap_mean(changes),
        'bootstrapReplicates': 2000, 'bootstrapSeed': 20261125})
    return result
