"""导出一批评分证据，供人工标注打分。

用法：

    python scripts/export_annotation_batch.py --size 40 --out annotation.csv

生成的 CSV 每行对应「一条证据（某个维度、某一轮）」，其中 human_score 留空待填，
填好后再跑 scripts/score_agreement.py 计算一致性。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import random
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.base import session_factory  # noqa: E402
from app.db.models import Evaluation, EvaluationEvidence, Message, TrainingSession  # noqa: E402

LABELS = {
    "logic": "内容与逻辑",
    "relevance": "贴合问题",
    "correctness": "信息完整",
    "concision": "表达干净",
}
SCORE_FIELD = {
    "logic": "logic_score",
    "relevance": "relevance_score",
    "correctness": "correctness_score",
    "concision": "concision_score",
}


async def collect(size: int) -> list[dict]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(EvaluationEvidence, Evaluation, Message, TrainingSession)
                .join(Evaluation, Evaluation.id == EvaluationEvidence.evaluation_id)
                .join(Message, Message.id == EvaluationEvidence.answer_message_id)
                .join(TrainingSession, TrainingSession.id == Evaluation.session_id)
                .where(Evaluation.degraded.is_(False))
            )
        ).all()
        question_ids = {row[0].question_message_id for row in rows if row[0].question_message_id}
        questions = {
            message.id: message.content
            for message in (
                await session.scalars(select(Message).where(Message.id.in_(question_ids)))
            ).all()
        } if question_ids else {}

    pool: list[dict] = []
    for evidence, evaluation, message, training in rows:
        dimension = evidence.dimension if evidence.dimension in SCORE_FIELD else None
        if dimension is None:
            continue
        pool.append(
            {
                "session_id": evaluation.session_id,
                "round_no": evidence.round_no,
                "dimension": LABELS[dimension],
                "dimension_key": dimension,
                "question": questions.get(evidence.question_message_id, ""),
                "answer": message.content,
                "quote": evidence.quote,
                "model_score": getattr(evaluation, SCORE_FIELD[dimension]),
                "channel": training.channel,
                "human_score": "",
                "note": "",
            }
        )

    # 按维度轮流抽样，保证四维都有样本
    random.seed(20261102)
    by_dimension: dict[str, list[dict]] = {}
    for row in pool:
        by_dimension.setdefault(row["dimension"], []).append(row)
    selected: list[dict] = []
    keys = list(by_dimension)
    while len(selected) < size and any(by_dimension.values()):
        for key in keys:
            bucket = by_dimension[key]
            if bucket and len(selected) < size:
                selected.append(bucket.pop(random.randrange(len(bucket))))
    return selected


async def main() -> None:
    parser = argparse.ArgumentParser(description="导出人工标注样本")
    parser.add_argument("--size", type=int, default=40)
    parser.add_argument("--out", default="annotation.csv")
    parser.add_argument("--blind", action="store_true", help="按完整报告导出四维盲评；size 表示报告数")
    parser.add_argument("--email", default=None, help="只导出指定账号的数据")
    parser.add_argument("--key-out", default="", help="盲评模型分对照文件，必须与标注表分开保存")
    args = parser.parse_args()

    if not 1 <= args.size <= 200:
        raise SystemExit("size 必须在 1–200 之间")
    if args.blind:
        from app.features.evaluations.blind_study import collect_blind
        async with session_factory() as db:
            annotations, key = await collect_blind(db, args.size, args.email)
        if not annotations:
            raise SystemExit("没有符合正式评分条件的完整报告，不能生成盲评材料")
        target = Path(args.out)
        key_target = Path(args.key_out) if args.key_out else target.with_name(target.stem + "-model-key.csv")
        if target.resolve() == key_target.resolve():
            raise SystemExit("盲评表与模型对照表不能使用同一路径")
        for path, values in ((target, annotations), (key_target, key)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(values[0]))
                writer.writeheader()
                writer.writerows(values)
        print(f"已准备 {len(annotations) // 4} 份独立报告、{len(annotations)} 条维度盲评，人工分数留空。")
        print(f"标注表：{target.resolve()}\n模型对照表（不交给盲评者）：{key_target.resolve()}")
        return

    rows = await collect(args.size)
    if not rows:
        print("没有可导出的证据（需要非降级评分记录）")
        return

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = ["session_id", "round_no", "dimension", "question", "answer", "quote", "model_score", "human_score", "note"]
    with target.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})

    print(f"已导出 {len(rows)} 条到 {target.resolve()}")
    print("下一步：用 Excel 打开，填写 human_score（1-5 整数），然后运行：")
    print(f"    python scripts/score_agreement.py --input {target.name}")


if __name__ == "__main__":
    asyncio.run(main())
