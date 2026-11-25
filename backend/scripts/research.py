"""Prepare and analyze calibration/study materials without writing business data."""
import argparse
import asyncio
import hashlib
import json
import sys
import time
import httpx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.features.evaluations.research import prepare_calibration, analyze_calibration, read_csv, write_csv
from app.features.evaluations.study import prepare_study, blind_study, analyze_study
from app.features.evaluations.schemas import EvaluationPayload
from app.features.evaluations.standards import DIMENSION_LABELS


async def score_calibration(pack: Path, split: str, limit: int, out: Path, release_holdout: bool):
    from app.infrastructure.llm import llm_gateway
    if split == 'holdout' and not release_holdout:
        raise ValueError('留出集只能在冻结评分方案后显式 --release-holdout；调参请使用 development')
    if not 1 <= limit <= 48:
        raise ValueError('--limit 必须为 1–48，默认仅 4 次调用')
    if out.exists() or out.with_suffix('.json').exists():
        raise ValueError('模型输出已存在，请使用新的输出路径以保留旧版本')
    if not llm_gateway.configured:
        raise ValueError('未配置模型，不能用本地兜底分数充当模型实验结果')
    standard = json.loads((pack / 'standard.json').read_text(encoding='utf-8'))
    if hashlib.sha256(standard['systemPrompt'].encode()).hexdigest() != standard['hash']:
        raise ValueError('评分标准正文与 hash 不匹配')
    samples = [json.loads(line) for line in (pack / 'private/samples.jsonl').read_text(encoding='utf-8').splitlines()]
    selected = [item for item in samples if item['split'] == split][:limit]
    key = read_csv(pack / 'private/key.csv')
    rows, attempts = [], []
    for sample in selected:
        started = time.perf_counter()
        try:
            if sample['standardHash'] != standard['hash']:
                raise ValueError('样本评分标准版本不匹配')
            raw = await llm_gateway.complete_json(standard['systemPrompt'],
                '这是编写的单题校准样本，只依据提供的回答评分；未知和缺失不能推测。'
                f"\n对话：\n第 1 轮对方：{sample['question']}\n第 1 轮用户：{sample['answer']}",
                temperature=0.2, max_tokens=5000)
            payload = EvaluationPayload.model_validate(raw)
            scores = payload.scores.model_dump()
            # Preserve full output for a coordinator to audit; never expose it to blind raters.
            attempts.append({'caseId': sample['id'], 'status': 'MODEL_ONLY_UNVALIDATED',
                             'seconds': round(time.perf_counter() - started, 3), 'output': raw})
            for row in key:
                if row['case_id'] == sample['id']:
                    rows.append({'sample_id': row['sample_id'], 'dimension': row['dimension'],
                                 'model_score': scores[row['dimension_key']], 'standard_hash': standard['hash']})
        except Exception as exc:
            code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            attempts.append({'caseId': sample['id'], 'status': 'FAILED', 'errorType': type(exc).__name__,
                             'httpStatus': code, 'seconds': round(time.perf_counter() - started, 3)})
            if code in {401, 402, 403, 429}:
                break  # Authentication, billing or throttling requires correction before more paid attempts.
    write_csv(out, rows, ['sample_id', 'dimension', 'model_score', 'standard_hash'])
    status = 'MODEL_ONLY_UNVALIDATED' if len(rows) == len(selected) * len(DIMENSION_LABELS) else 'INCOMPLETE_MODEL_RESULTS'
    result = {'status': status, 'model': llm_gateway.config.llm_model,
              'standardHash': standard['hash'], 'split': split, 'requestedCases': len(selected),
              'successfulCases': len(rows) // len(DIMENSION_LABELS), 'attempts': attempts,
              'usage': 'See provider billing; this tool does not estimate unreported tokens or cost.',
              'note': '单题原始模型输出，不等同完整会话正式报告或真人一致性结果。'}
    out.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return {key: value for key, value in result.items() if key != 'attempts'}


def parser():
    root = argparse.ArgumentParser(description='离线研究材料：所有人工分数默认留空，不修改业务数据库')
    commands = root.add_subparsers(dest='command', required=True)
    for name in ('prepare-calibration', 'prepare-study'):
        command = commands.add_parser(name)
        command.add_argument('--out', type=Path, required=True, help='必须是不存在的新目录，防止覆盖人工数据')
        if name == 'prepare-study':
            command.add_argument('--slots', type=int, default=12)
    for name in ('analyze-calibration', 'score-calibration', 'blind-study', 'analyze-study'):
        command = commands.add_parser(name)
        command.add_argument('--pack', type=Path, required=True)
        if name in ('analyze-calibration', 'score-calibration'):
            command.add_argument('--split', choices=['development', 'holdout'], default='development')
        if name == 'analyze-calibration':
            command.add_argument('--model', type=Path)
        if name == 'score-calibration':
            command.add_argument('--limit', type=int, default=4)
            command.add_argument('--release-holdout', action='store_true')
        if name == 'analyze-study':
            command.add_argument('--blind', type=Path)
        command.add_argument('--out', type=Path, required=True)
    return root


def main():
    args = parser().parse_args()
    try:
        if args.command == 'prepare-calibration':
            result = prepare_calibration(args.out)
        elif args.command == 'prepare-study':
            result = prepare_study(args.out, args.slots)
        elif args.command == 'blind-study':
            result = blind_study(args.pack, args.out)
        elif args.command == 'score-calibration':
            result = asyncio.run(score_calibration(args.pack, args.split, args.limit, args.out, args.release_holdout))
        else:
            result = analyze_calibration(args.pack, args.split, args.model) if args.command == 'analyze-calibration' else analyze_study(args.pack, args.blind)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f'未执行：{exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get('status') == 'INCOMPLETE_MODEL_RESULTS' else 0


if __name__ == '__main__':
    raise SystemExit(main())
