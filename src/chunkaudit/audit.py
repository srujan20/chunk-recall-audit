"""One chunking audited: the ceiling, the gap, and the verdict that follows.

Three verdicts, and the ordering between them is deliberate. Unattributable
questions are checked first, because a corpus where the causes cannot be told
apart cannot support a statement about which cause dominates, and saying so is
more useful than picking one. Only then is the ceiling compared to its floor.

The audit reports the ceiling before it reports any retrieval number, which is
the order the finding actually has. The ceiling is a property of the chunker and
is decided before a single vector is computed; every retrieval figure below it is
conditional on a choice that has already been made.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .ceiling import CeilingReport
from .config import Policy
from .metrics import Cause, MetricSet, Rate


class Verdict(str, Enum):
    SURVIVES = "answers-survive-the-chunker"
    DESTROYING = "chunker-destroys-material-answers"
    UNATTRIBUTABLE = "causes-cannot-be-told-apart"


EXIT_CODES = {
    Verdict.SURVIVES: 0,
    Verdict.DESTROYING: 1,
    Verdict.UNATTRIBUTABLE: 2,
}


@dataclass(frozen=True)
class AuditResult:
    """Everything one audit produced, with the ceiling separated from the metrics."""

    chunking: str
    retriever: str
    k: int
    ceiling: CeilingReport
    metrics: MetricSet
    verdict: Verdict
    ceiling_floor: float
    material_gap: float

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.verdict]

    @property
    def unattributable(self) -> Rate:
        return Rate(
            sum(1 for item in self.metrics.outcomes if item.cause is Cause.UNATTRIBUTABLE),
            self.metrics.questions,
        )

    @property
    def headroom(self) -> float:
        """How far the measured span complete recall sits below the ceiling.

        This is the only part of the shortfall a retriever change can address. The
        rest is the chunker's, and no amount of retrieval work reaches it.
        """
        return self.ceiling.ceiling - self.metrics.span_complete_recall.value

    @property
    def attainable_share(self) -> float:
        """Share of the total shortfall that a perfect retriever would recover."""
        shortfall = 1.0 - self.metrics.span_complete_recall.value
        if shortfall <= 0.0:
            return 0.0
        return self.headroom / shortfall

    def as_dict(self) -> dict[str, object]:
        return {
            "chunking": self.chunking,
            "retriever": self.retriever,
            "k": self.k,
            "verdict": self.verdict.value,
            "exit_code": self.exit_code,
            "ceiling": self.ceiling.as_dict(),
            "metrics": self.metrics.as_dict(),
            "ceiling_floor": self.ceiling_floor,
            "material_gap": self.material_gap,
            "headroom": self.headroom,
            "attainable_share": self.attainable_share,
            "unattributable": self.unattributable.as_dict(),
        }


def decide_verdict(ceiling: float, gap: float, unattributable: float, policy: Policy) -> Verdict:
    """Combine the three quantities into one outcome."""
    if unattributable > policy.audit.unattributable_tolerance:
        return Verdict.UNATTRIBUTABLE
    if ceiling < policy.audit.ceiling_floor or gap >= policy.audit.material_gap:
        return Verdict.DESTROYING
    return Verdict.SURVIVES


def audit(ceiling: CeilingReport, metrics: MetricSet, policy: Policy) -> AuditResult:
    unattributable = Rate(
        sum(1 for item in metrics.outcomes if item.cause is Cause.UNATTRIBUTABLE),
        metrics.questions,
    )
    return AuditResult(
        chunking=ceiling.chunking,
        retriever=metrics.retriever,
        k=metrics.k,
        ceiling=ceiling,
        metrics=metrics,
        verdict=decide_verdict(ceiling.ceiling, metrics.gap, unattributable.value, policy),
        ceiling_floor=policy.audit.ceiling_floor,
        material_gap=policy.audit.material_gap,
    )
