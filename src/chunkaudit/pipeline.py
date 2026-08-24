"""Running the whole audit, and the row type every experiment reduces.

One place builds the corpus, the chunkings, the rankings and the metrics, so five
experiments cannot disagree about how a figure was produced. The row type carries
the chunking parameters alongside every rate, because a ceiling without its size
and stride is not a number anybody can act on.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .audit import AuditResult, audit
from .ceiling import CeilingReport, ceiling_report
from .chunking import PLAN, Chunking, build_chunking
from .config import Policy
from .documents import Corpus, build_corpus
from .metrics import evaluate
from .retrieval import RUNNABLE, Ranking, rank


@dataclass(frozen=True)
class AuditRow:
    """One audited combination, flattened to the columns the documents quote."""

    chunking: str
    strategy: str
    size: int
    stride: int
    overlap: int
    guaranteed_length: int | None
    chunk_count: int
    retriever: str
    k: int
    questions: int
    ceiling: float
    chunk_recall: float
    span_complete_recall: float
    assembled_recall: float
    overstated: float
    gap: float
    fixable_by_retriever: float
    destroyed_by_chunking: int
    missed_by_retrieval: int
    unattributable: int
    headroom: float
    attainable_share: float
    median_retrieved_share: float
    verdict: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def row_from(result: AuditResult) -> AuditRow:
    metrics = result.metrics
    causes = metrics.causes
    return AuditRow(
        chunking=result.chunking,
        strategy=result.ceiling.strategy,
        size=result.ceiling.size,
        stride=result.ceiling.stride,
        overlap=result.ceiling.overlap,
        guaranteed_length=result.ceiling.guaranteed_length,
        chunk_count=result.ceiling.chunk_count,
        retriever=result.retriever,
        k=result.k,
        questions=metrics.questions,
        ceiling=result.ceiling.ceiling,
        chunk_recall=metrics.chunk_recall.value,
        span_complete_recall=metrics.span_complete_recall.value,
        assembled_recall=metrics.assembled_recall.value,
        overstated=metrics.overstated.value,
        gap=metrics.gap,
        fixable_by_retriever=metrics.fixable_by_retriever.value,
        destroyed_by_chunking=causes["chunking-destroyed-it"],
        missed_by_retrieval=causes["retrieval-missed-it"],
        unattributable=causes["unattributable"],
        headroom=result.headroom,
        attainable_share=result.attainable_share,
        median_retrieved_share=metrics.median_retrieved_share,
        verdict=result.verdict.value,
    )


def corpus_for(policy: Policy) -> Corpus:
    return build_corpus(
        documents=policy.corpus.documents,
        questions_per_document=policy.corpus.questions_per_document,
        span_chars=policy.corpus.span_chars,
    )


def chunkings_for(corpus: Corpus, plan: tuple[tuple[str, int, int], ...] = PLAN) -> list[Chunking]:
    return [build_chunking(corpus.documents, *entry) for entry in plan]


def run_audit(
    corpus: Corpus,
    chunking: Chunking,
    policy: Policy,
    *,
    retriever: str,
    k: int,
    rankings: list[Ranking] | None = None,
    ceiling: CeilingReport | None = None,
) -> AuditResult:
    """Audit one chunking with one retriever at one k."""
    resolved_ceiling = ceiling if ceiling is not None else ceiling_report(corpus, chunking)
    resolved_rankings = (
        rankings if rankings is not None else rank(retriever, corpus, chunking, policy)
    )
    metrics = evaluate(corpus, chunking, resolved_rankings, retriever=retriever, k=k)
    return audit(resolved_ceiling, metrics, policy)


def sweep(
    policy: Policy,
    *,
    plan: tuple[tuple[str, int, int], ...] = PLAN,
    retrievers: tuple[str, ...] = RUNNABLE,
    ks: tuple[int, ...] | None = None,
    corpus: Corpus | None = None,
) -> list[AuditRow]:
    """Audit every combination of chunking, retriever and k.

    Rankings are computed once per chunking and retriever and reused across the k
    values, because a ranking does not depend on k. The first version recomputed
    them per k and spent four fifths of the audit's runtime re-ranking the same
    chunks five times.
    """
    resolved_corpus = corpus if corpus is not None else corpus_for(policy)
    resolved_ks = ks if ks is not None else policy.retrieval.sweep_k
    rows: list[AuditRow] = []
    for chunking in chunkings_for(resolved_corpus, plan):
        report = ceiling_report(resolved_corpus, chunking)
        for retriever in retrievers:
            rankings = rank(retriever, resolved_corpus, chunking, policy)
            for k in resolved_ks:
                rows.append(
                    row_from(
                        run_audit(
                            resolved_corpus,
                            chunking,
                            policy,
                            retriever=retriever,
                            k=k,
                            rankings=rankings,
                            ceiling=report,
                        )
                    )
                )
    return rows
