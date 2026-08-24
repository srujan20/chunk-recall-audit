"""Shared setup for the five experiments.

There is no cache here, and that is worth a sentence. The whole sweep of thirteen
chunkings by four retrievers by five values of k runs in under ten seconds,
because the expensive part of a retrieval evaluation is usually the encoder and
this repository does not have one. The ceiling in particular costs nothing at all:
it is interval arithmetic over character offsets. A team can compute the number
that bounds every retriever it will ever try before it picks one.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(REPO / "src"))

from chunkaudit.ceiling import ceiling_report  # noqa: E402
from chunkaudit.chunking import PLAN, build_chunking  # noqa: E402
from chunkaudit.config import Policy, load_policy  # noqa: E402
from chunkaudit.documents import Corpus  # noqa: E402
from chunkaudit.pipeline import AuditRow, corpus_for, sweep  # noqa: E402
from chunkaudit.retrieval import RUNNABLE  # noqa: E402

RESULTS_DIRECTORY = REPO / "docs" / "experiments"
COMMON_DEFAULTS = ("fixed-200-200", "fixed-400-400", "fixed-800-800")


def setup() -> tuple[Policy, Corpus]:
    policy = load_policy()
    return policy, corpus_for(policy)


def full_sweep(policy: Policy, corpus: Corpus) -> list[AuditRow]:
    return sweep(policy, retrievers=RUNNABLE, corpus=corpus)


def at(rows: list[AuditRow], *, retriever: str, k: int) -> list[AuditRow]:
    return [row for row in rows if row.retriever == retriever and row.k == k]


def by_chunking(rows: list[AuditRow]) -> dict[str, AuditRow]:
    return {row.chunking: row for row in rows}


def _finite(value: object) -> object:
    """Replace a non finite float with None so the JSON stays valid everywhere."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite(item) for item in value]
    return value


def write_result(name: str, payload: dict[str, object]) -> Path:
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = RESULTS_DIRECTORY / f"{name}.json"
    destination.write_text(
        json.dumps(_finite(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return destination


def table(headers: list[str], rows: list[list[object]]) -> str:
    widths = [len(head) for head in headers]
    rendered = [[str(cell) for cell in row] for row in rows]
    for row in rendered:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    line = "  ".join(head.ljust(widths[index]) for index, head in enumerate(headers))
    rule = "  ".join("-" * widths[index] for index in range(len(headers)))
    body = [
        "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)) for row in rendered
    ]
    return "\n".join([line, rule, *body])


def pct(value: float, digits: int = 1) -> str:
    if value != value:
        return "n/a"
    return f"{100.0 * value:.{digits}f}%"


__all__ = [
    "COMMON_DEFAULTS",
    "PLAN",
    "REPO",
    "RUNNABLE",
    "at",
    "build_chunking",
    "by_chunking",
    "ceiling_report",
    "full_sweep",
    "pct",
    "setup",
    "table",
    "write_result",
]
