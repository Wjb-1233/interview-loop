"""读取人工标注结果，计算与模型评分的一致性。

用法：

    python scripts/score_agreement.py --input annotation.csv --report docs/评分一致性.md
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.features.evaluations.agreement import by_dimension, render_markdown, summarize  # noqa: E402


def load(path: Path, key_path: Path | None = None) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    problems: list[str] = []
    model_rows = {}
    if key_path:
        with key_path.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                identity = row.get("sample_id")
                if not identity or identity in model_rows:
                    raise ValueError("模型对照表存在缺失或重复 sample_id")
                model_rows[identity] = row
    seen = set()
    with path.open(encoding="utf-8-sig") as handle:
        for index, row in enumerate(csv.DictReader(handle), start=2):
            raw = (row.get("human_score") or "").strip()
            if not raw:
                continue
            try:
                human = float(raw)
            except ValueError:
                problems.append(f"第 {index} 行 human_score 不是数字：{raw}")
                continue
            if not 1 <= human <= 5:
                problems.append(f"第 {index} 行分数超出 1-5：{human}")
                continue
            identity = row.get("sample_id")
            if key_path and (identity not in model_rows or identity in seen):
                problems.append(f"第 {index} 行 sample_id 缺少对照或重复，未计入")
                continue
            paired = model_rows.get(identity, row) if key_path else row
            if key_path and paired.get("dimension") != row.get("dimension"):
                problems.append(f"第 {index} 行维度与模型对照不一致，未计入")
                continue
            try:
                model = float(paired.get("model_score") or 0)
            except ValueError:
                problems.append(f"第 {index} 行 model_score 异常")
                continue
            if not math.isfinite(model) or not 1 <= model <= 5:
                problems.append(f"第 {index} 行 model_score 超出 1–5，未计入")
                continue
            seen.add(identity)
            rows.append({"dimension": row.get("dimension") or "未知", "model": model, "human": human,
                         "group_id": paired.get("group_id") or paired.get("session_id")})
    return rows, problems


def main() -> None:
    parser = argparse.ArgumentParser(description="计算评分一致性")
    parser.add_argument("--input", default="annotation.csv")
    parser.add_argument("--report", default="")
    parser.add_argument("--key", default="", help="盲评配对所需的模型对照表")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.is_file():
        raise SystemExit(f"找不到文件：{path}")

    rows, problems = load(path, Path(args.key) if args.key else None)
    if not rows:
        raise SystemExit("没有填写的 human_score，无法统计")

    overall = summarize([(row["model"], row["human"]) for row in rows])
    per_dimension = by_dimension(rows)
    markdown = render_markdown(overall, per_dimension, len(rows))
    groups = {row["group_id"] for row in rows if row.get("group_id")}
    if groups:
        markdown += f"\n\n独立报告数：{len(groups)}。同一报告的四维标注不视为四个独立训练样本。\n"

    print(markdown)
    for problem in problems:
        print("  提示:", problem)

    if args.report:
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        print(f"\n报告已写入 {target}")


if __name__ == "__main__":
    main()
