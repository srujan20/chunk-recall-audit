"""The command line interface, and the exit codes it promises.

    0  the audit ran and the answers survive this chunking
    1  the audit ran and the chunker destroys material answers
    2  the audit ran and the causes cannot be told apart, so a human is needed
    3  the audit could not run: a corpus with no questions, an answer span outside
       its document, or a chunking that produced nothing for a document with text
    4  the invocation was wrong: an unknown strategy or retriever, a stride larger
       than its size, a policy that will not load, or an optional retriever that
       is not installed

The separation between 0 and 3 is the point. A tool that returns the same code for
"the answers survived" and "I could not check" is a tool whose zero means nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .chunking import PLAN, build_chunking
from .config import Policy, load_policy
from .errors import MissingDependencyError, PolicyError, UnanswerableError, UsageError
from .pipeline import AuditRow, corpus_for, run_audit, sweep
from .report import render_html, render_sweep_html, render_text
from .retrieval import RUNNABLE, WRITTEN_NOT_RUN

EXIT_UNANSWERABLE = 3
EXIT_USAGE = 4
STRATEGIES = ("fixed", "sentence", "recursive", "document")


def _write(path: str | None, payload: str) -> None:
    if path is None:
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(payload, encoding="utf-8")


def _policy(args: argparse.Namespace) -> Policy:
    return load_policy(getattr(args, "policy", None))


def command_plan(args: argparse.Namespace) -> int:
    policy = _policy(args)
    corpus = corpus_for(policy)
    rows = []
    for strategy, size, stride in PLAN:
        chunking = build_chunking(corpus.documents, strategy, size, stride)
        rows.append(
            {
                "chunking": chunking.name,
                "strategy": strategy,
                "size": size,
                "stride": stride,
                "overlap": chunking.overlap,
                "chunks": chunking.count,
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    width = max(len(row["chunking"]) for row in rows)
    print(f"{'chunking'.ljust(width)}  {'chunks':>7}  {'overlap':>7}")
    for row in rows:
        print(f"{row['chunking'].ljust(width)}  {row['chunks']:>7}  {row['overlap']:>7}")
    print()
    print(f"corpus: {policy.corpus.documents} documents, {policy.corpus.questions} questions")
    print(f"retrievers that run here: {', '.join(RUNNABLE)}")
    print(f"written and never run in this environment: {', '.join(WRITTEN_NOT_RUN)} (see ADR-003)")
    return 0


def command_audit(args: argparse.Namespace) -> int:
    policy = _policy(args)
    corpus = corpus_for(policy)
    chunking = build_chunking(corpus.documents, args.strategy, args.size, args.stride)
    result = run_audit(corpus, chunking, policy, retriever=args.retriever, k=args.k)
    print(render_text(result), end="")
    _write(args.html, render_html(result))
    if args.json:
        _write(args.json, json.dumps(result.as_dict(), indent=2) + "\n")
    return result.exit_code


def _print_sweep(rows: list[AuditRow], retriever: str, k: int) -> None:
    selected = sorted(
        (row for row in rows if row.retriever == retriever and row.k == k),
        key=lambda row: row.ceiling,
    )
    print(f"{len(rows)} audited combinations, showing {retriever} at k={k}")
    print()
    header = (
        f"  {'chunking':<20}{'chunks':>7}{'ovl':>5}{'guar':>6}{'ceiling':>9}"
        f"{'chunkR':>8}{'spanR':>8}{'gap':>8}{'destroyed':>10}{'missed':>7}"
    )
    print(header)
    for row in selected:
        guaranteed = "n/a" if row.guaranteed_length is None else str(row.guaranteed_length)
        print(
            f"  {row.chunking:<20}{row.chunk_count:>7}{row.overlap:>5}{guaranteed:>6}"
            f"{row.ceiling:>9.4f}{row.chunk_recall:>8.4f}{row.span_complete_recall:>8.4f}"
            f"{row.gap:>8.4f}{row.destroyed_by_chunking:>10}{row.missed_by_retrieval:>7}"
        )
    print()
    destroyed = sum(row.destroyed_by_chunking for row in selected)
    missed = sum(row.missed_by_retrieval for row in selected)
    total = destroyed + missed
    if total:
        print(
            f"across these chunkings, {missed} of {total} failures could be fixed by a "
            f"better retriever, which is {missed / total:.4f}"
        )
    print("the ceiling column bounds every retriever, including one this build cannot run")


def command_sweep(args: argparse.Namespace) -> int:
    policy = _policy(args)
    rows = sweep(
        policy,
        retrievers=tuple(args.retrievers),
        ks=tuple(args.ks) if args.ks else None,
    )
    _print_sweep(rows, args.retrievers[0], args.k)
    _write(args.html, render_sweep_html(rows, retriever=args.retrievers[0], k=args.k))
    if args.json:
        _write(args.json, json.dumps([row.as_dict() for row in rows], indent=2) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chunkaudit",
        description=(
            "Report the answers a chunker destroyed, which a retrieval metric computed on "
            "its chunks cannot see. Exit codes: 0 the answers survive, 1 the chunker "
            "destroys material answers, 2 the causes cannot be told apart, 3 the audit "
            "could not run, 4 the invocation was wrong."
        ),
    )
    parser.add_argument("--version", action="version", version=f"chunkaudit {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="list the chunkings and the retrievers")
    plan_parser.add_argument("--json", action="store_true")
    plan_parser.add_argument("--policy")
    plan_parser.set_defaults(handler=command_plan)

    audit_parser = subparsers.add_parser("audit", help="audit one chunking")
    audit_parser.add_argument("--strategy", default="fixed", choices=STRATEGIES)
    audit_parser.add_argument("--size", type=int, default=400)
    audit_parser.add_argument("--stride", type=int, default=400)
    audit_parser.add_argument("--retriever", default="bm25", choices=[*RUNNABLE, *WRITTEN_NOT_RUN])
    audit_parser.add_argument("--k", type=int, default=5)
    audit_parser.add_argument("--policy")
    audit_parser.add_argument("--html")
    audit_parser.add_argument("--json")
    audit_parser.set_defaults(handler=command_audit)

    sweep_parser = subparsers.add_parser("sweep", help="audit every chunking in the plan")
    sweep_parser.add_argument("--retrievers", nargs="+", default=list(RUNNABLE), choices=RUNNABLE)
    sweep_parser.add_argument("--ks", type=int, nargs="+", default=[])
    sweep_parser.add_argument("--k", type=int, default=5, help="the k the tables display")
    sweep_parser.add_argument("--policy")
    sweep_parser.add_argument("--html")
    sweep_parser.add_argument("--json")
    sweep_parser.set_defaults(handler=command_sweep)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (UsageError, PolicyError, MissingDependencyError) as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except UnanswerableError as exc:
        print(f"cannot answer: {exc}", file=sys.stderr)
        return EXIT_UNANSWERABLE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
