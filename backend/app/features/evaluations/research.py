"""Research materials and strict two-rater calibration; never invent human scores."""
import csv
import hashlib
import json
import random
from pathlib import Path

from app.features.evaluations.agreement import summarize
from app.features.evaluations.standards import current_standard, DIMENSION_LABELS
from app.features.training.question_catalog import QUESTIONS, CATALOG_VERSION, transfer_specs

RATER_FIELDS = ["sample_id", "dimension", "conversation", "human_score", "note"]


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def ordinal(value: str, location: str) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{location}: 分数必须是 1–5 整数') from None
    if number not in {1, 2, 3, 4, 5}:
        raise ValueError(f'{location}: 分数必须是 1–5 整数')
    return int(number)


def indexed(rows: list[dict], name: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        identity = row.get('sample_id', '').strip()
        if not identity or identity in result:
            raise ValueError(f'{name}: 缺少或重复 sample_id')
        result[identity] = row
    return result


def require_independent_raters(directory: Path):
    raters = json.loads((directory / 'raters.json').read_text(encoding='utf-8'))
    a, b = (str(raters.get(name, '')).strip() for name in ('raterA', 'raterB'))
    if not a or not b or a.casefold() == b.casefold():
        raise ValueError('raters.json 须记录两位不同评审的匿名编号，不能同一人填两份表')


def load_rater(path: Path, expected: dict[str, dict]) -> dict[str, int | None]:
    rows = indexed(read_csv(path), path.name)
    if set(rows) != set(expected):
        raise ValueError(f'{path.name}: 题目集合被改动，必须保留全部 sample_id')
    scores = {}
    for identity, row in rows.items():
        target = expected[identity]
        if row.get('dimension') != target['dimension']:
            raise ValueError(f'{identity}: 维度不匹配')
        if target.get('conversation') and row.get('conversation') != target['conversation']:
            raise ValueError(f'{identity}: 回答正文被改动，不能与原样本配对')
        scores[identity] = ordinal(row.get('human_score'), identity)
        if scores[identity] is not None and not row.get('conversation', '').strip():
            raise ValueError(f'{identity}: 没有真实回答正文，不能填分')
    return scores


def prepare_calibration(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    standard = current_standard()
    (directory / 'raters.json').write_text(json.dumps({'raterA': '', 'raterB': ''}, indent=2), encoding='utf-8')
    samples, labels, key = [], [], []
    for question in QUESTIONS:
        for case_type, answer in question['answers'].items():
            sample = {'id': question['id'] + '-' + case_type, 'familyId': question['id'],
                      'split': question['split'], 'competencyId': question['competencyId'],
                      'question': question['question'], 'answer': answer, 'caseType': case_type,
                      'source': 'AUTHORED_SYNTHETIC', 'standardHash': standard['hash']}
            samples.append(sample)
            group = hashlib.sha256(sample['id'].encode()).hexdigest()[:12]
            conversation = f"问：{sample['question']}\n答：{answer}"
            for dimension, label in DIMENSION_LABELS.items():
                identity = group + '-' + dimension
                labels.append({'sample_id': identity, 'dimension': label, 'conversation': conversation,
                               'human_score': '', 'note': ''})
                key.append({'sample_id': identity, 'group_id': group, 'case_id': sample['id'],
                            'family_id': question['id'], 'split': sample['split'], 'dimension': label,
                            'dimension_key': dimension, 'case_type': case_type, 'model_score': '',
                            'standard_hash': standard['hash'], 'source': sample['source']})
    for rater, seed in [('a', 20261125), ('b', 20261126)]:
        shuffled = list(labels)
        random.Random(seed).shuffle(shuffled)
        write_csv(directory / f'rater_{rater}.csv', shuffled)
    write_csv(directory / 'private/key.csv', key)
    private = directory / 'private'
    (private / 'samples.jsonl').write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in samples), encoding='utf-8')
    (directory / 'standard.json').write_text(json.dumps(standard, ensure_ascii=False, indent=2), encoding='utf-8')
    (directory / 'standard.md').write_text('# 冻结评分标准\n\n版本：' + standard['id'] + '\n\n'
        + standard['systemPrompt'] + '\n\n人工校准状态：待采集。\n', encoding='utf-8')
    catalog = [{key: value for key, value in question.items() if key != 'answers'} for question in QUESTIONS]
    (directory / 'questions.json').write_text(json.dumps({'version': CATALOG_VERSION, 'reviewStatus': 'AUTHOR_DRAFT',
        'questions': catalog, 'transferQuestions': [item for domain in ('project','transaction','cache','diagnosis') for item in transfer_specs(domain)]}, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = {'schemaVersion': 1, 'standardId': standard['id'], 'standardHash': standard['hash'],
                'sampleCount': len(samples), 'questionFamilies': len(QUESTIONS),
                'developmentCases': sum(item['split'] == 'development' for item in samples),
                'holdoutCases': sum(item['split'] == 'holdout' for item in samples),
                'source': 'AUTHORED_SYNTHETIC', 'humanLabelsCollected': 0,
                'status': 'AWAITING_HUMAN_LABELS', 'reviewStatus': 'AUTHOR_DRAFT',
                'holdoutPolicy': '按题目整组划分；调参期间只使用 development。case_type 是编写意图，不是专家金标准。'}
    (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (directory / 'README.md').write_text(
        '# 评分校准材料\n\n48 份人工编写的合成回答，不是真人数据。两位评审分别填写 rater_a.csv、rater_b.csv，只改 human_score 和 note。\n\n'
        '评分前阅读 standard.json 的四维行为锚点；每项填 1–5 整数。不得互看评分、模型分或 private 目录。\n\n'
        'private 目录由研究负责人保管。开发集与留出集按题目划分；留出集只在评分方案冻结后验收。\n\n'
        '所有人工分数留空。空白表只能得到“待采集”，不能生成一致率或训练有效性结论。题目难度与评分标准尚待真人审核。\n', encoding='utf-8')
    return manifest


def analyze_calibration(directory: Path, split: str = 'development', model_path: Path | None = None) -> dict:
    if split not in {'development', 'holdout'}:
        raise ValueError('只允许 development 或 holdout')
    key = indexed(read_csv(directory / 'private/key.csv'), 'key')
    expected = {}
    # Reconstruct immutable question text instead of trusting a modified rater A.
    samples = {row['id']: row for row in [json.loads(line) for line in (directory / 'private/samples.jsonl').read_text(encoding='utf-8').splitlines()]}
    for identity, row in key.items():
        sample = samples[row['case_id']]
        expected[identity] = {'dimension': row['dimension'], 'conversation': f"问：{sample['question']}\n答：{sample['answer']}"}
    a, b = load_rater(directory / 'rater_a.csv', expected), load_rater(directory / 'rater_b.csv', expected)
    selected = [identity for identity, row in key.items() if row['split'] == split]
    complete = all(a[identity] is not None and b[identity] is not None for identity in selected)
    output = {'status': 'HUMAN_LABELS_COMPLETE' if complete else 'AWAITING_HUMAN_LABELS', 'split': split,
              'answerCases': len({key[i]['group_id'] for i in selected}),
              'questionFamilies': len({key[i]['family_id'] for i in selected}),
              'expectedRatingsPerRater': len(selected),
              'raterACompleted': sum(a[i] is not None for i in selected),
              'raterBCompleted': sum(b[i] is not None for i in selected),
              'perDimension': {}, 'modelComparison': None,
              'note': '编写样本不等同真人样本；同题多种回答、同回答四维均不当作独立受试者。'}
    if not complete:
        return output
    require_independent_raters(directory)
    disagreements = []
    for dimension in DIMENSION_LABELS.values():
        ids = [i for i in selected if key[i]['dimension'] == dimension]
        output['perDimension'][dimension] = summarize([(a[i], b[i]) for i in ids])
        disagreements.extend(i for i in ids if a[i] != b[i])
    output['needsAdjudication'] = disagreements
    if model_path:
        model = indexed(read_csv(model_path), 'model')
        if not set(selected) <= set(model):
            output['modelComparisonStatus'] = 'INCOMPLETE_MODEL_RESULTS'
            return output
        scores = {}
        for identity in selected:
            row = model[identity]
            if row.get('dimension') != key[identity]['dimension'] or row.get('standard_hash') != key[identity]['standard_hash']:
                raise ValueError(f'{identity}: 模型维度或评分标准版本不匹配')
            scores[identity] = ordinal(row.get('model_score'), identity)
        if any(value is None for value in scores.values()):
            output['modelComparisonStatus'] = 'INCOMPLETE_MODEL_RESULTS'
            return output
        output['modelComparison'] = {dimension: {
            'vsRaterA': summarize([(scores[i], a[i]) for i in selected if key[i]['dimension'] == dimension]),
            'vsRaterB': summarize([(scores[i], b[i]) for i in selected if key[i]['dimension'] == dimension])}
            for dimension in DIMENSION_LABELS.values()}
    return output
