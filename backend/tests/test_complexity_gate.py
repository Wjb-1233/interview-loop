"""Complexity ratchet: no function may get more complex than its recorded baseline.

Functions not in the baseline must stay at or below NEW_FUNCTION_LIMIT.
After simplifying code, lower the numbers with:  python -m tests.test_complexity_gate --update
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
BASELINE = Path(__file__).with_name("complexity_baseline.json")
NEW_FUNCTION_LIMIT = 15
RECORD_FROM = NEW_FUNCTION_LIMIT + 1  # functions at or above this go into the baseline

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_BRANCHES = (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.match_case)


def _own_nodes(function: ast.AST):
    """Nodes of this function, not descending into nested functions or lambdas."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (*_FUNCTIONS, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def complexity(function: ast.AST) -> int:
    score = 1
    for node in _own_nodes(function):
        if isinstance(node, _BRANCHES):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            score += 1 + len(node.ifs)
    return score


def measure() -> dict[str, int]:
    result: dict[str, int] = {}

    def visit(node: ast.AST, path: str, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _FUNCTIONS):
                name = f"{prefix}{child.name}"
                result[f"{path}::{name}"] = complexity(child)
                visit(child, path, f"{name}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, path, f"{prefix}{child.name}.")
            else:
                visit(child, path, prefix)

    for file in sorted(APP.rglob("*.py")):
        visit(ast.parse(file.read_text(encoding="utf-8")), file.relative_to(ROOT).as_posix(), "")
    return result


def test_function_complexity_does_not_regress():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    regressions = []
    for key, value in measure().items():
        limit = baseline.get(key, NEW_FUNCTION_LIMIT)
        if value > limit:
            regressions.append(f"{key}: {value} > {limit}")
    assert not regressions, "复杂度超过基线（拆分函数，或在确有必要时更新基线）：\n" + "\n".join(regressions)


if __name__ == "__main__":
    if "--update" not in sys.argv:
        sys.exit("usage: python -m tests.test_complexity_gate --update")
    current = {key: value for key, value in measure().items() if value >= RECORD_FROM}
    BASELINE.write_text(json.dumps(dict(sorted(current.items(), key=lambda item: (-item[1], item[0]))), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"baseline written: {len(current)} functions")
