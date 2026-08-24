"""Fail the build when a document quotes a figure the code no longer produces.

Two checks, in both directions.

The forward check: every metric in docs/metrics.json must appear in at least one
checked document, using one of its anchor phrases with the value substituted in.
Matching happens on phrases rather than on bare digits because a digit search
passes while the sentence around it has gone stale: "10 requests" is found in a
document that now says "10 rows". Anchors are alternatives, so any one matching
is enough, since the same figure reads differently in a table and in a
paragraph.

The reverse check: any number in the prose of a checked document that matches no
metric is reported, because that is a number nothing re-measures. Fenced code
blocks, inline code spans, HTML attributes and link targets are excluded, since
an example invocation is allowed to contain a made up row count and flagging it
would train the reader to ignore the section. Numbers that come from the policy
file, and a short list of structural numbers such as the fold counts, are
allowed. The reverse check reports by default and fails only with --strict,
because a check that legitimately fails gets deleted or weakened within a week.

Usage:
    python tools/check_numbers.py [--strict] [--summary PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
METRICS = REPO / "docs" / "metrics.json"
POLICY = REPO / "configs" / "policy.yaml"

FENCE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
HTML_ATTRIBUTE = re.compile(r"""\w+="[^"]*\"""")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w])")
WHITESPACE = re.compile(r"\s+")

# Structural numbers that are part of the design rather than measurements, each
# with the reason it is not something the code re-measures.
STRUCTURAL_NUMBERS = {
    "0": "a count of zero in prose",
    "1": "a single item, or an exit code",
    "2": "an exit code, or a pair",
    "3": "an exit code",
    "4": "an exit code",
    "5": "the default top k",
    "10": "a k value in the sweep",
    "20": "a k value in the sweep",
    "13": "chunkings in the plan",
    "40": "an answer length band, in characters",
    "150": "an answer length band, in characters",
    "400": "an answer length band and a chunk size, in characters",
    "200": "a chunk size or stride, in characters",
    "300": "a chunk stride, in characters",
    "600": "a chunk stride, in characters",
    "800": "a chunk size, in characters",
    "4096": "encoder dimensions",
    "4000": "the synthetic document length in exp03",
    "0.95": "the configured ceiling floor",
    "0.02": "the configured material gap",
    "101": "the guarantee length at size four hundred and stride three hundred",
    "102": "one character above that guarantee",
    "001": "an ADR number",
    "002": "an ADR number",
    "003": "an ADR number",
    "004": "an ADR number",
    "005": "an ADR number",
    "3.11": "a supported Python version",
    "3.12": "a supported Python version",
    "3.13": "a supported Python version",
    "6": "a claim heading number in the README",
    "7": "a claim heading number in the README",
    "25": "an answer length in the survival table",
    "50": "an answer length in the survival table, and a stride",
    "201": "an answer length in the survival table",
    "250": "an answer length in the survival table",
    "1200": "a window start in the non monotonicity worked example",
    "710": "a window start bound in the non monotonicity worked example",
    "810": "a window start bound in the non monotonicity worked example",
    "4200": "an illustrative offset in ADR-002",
    "4380": "an illustrative offset in ADR-002",
    "4600": "an illustrative offset in ADR-002",
    "4790": "an illustrative offset in ADR-002",
    "403": "the HTTP status the model weights host returns",
    "4.5": "the contrast ratio the screenshot tool enforces",
    "30": "the length in seconds of the defense guide opening",
    "24": "an illustrative percentage in ADR-004",
    # The two values below are history rather than measurements. They are the
    # figures the ceiling violation produced before it was fixed, quoted in the
    # war story. They are deliberately not re-measured: the bug is gone, so no
    # run of this code can produce them, and pinning them to a metric would mean
    # keeping the bug alive to measure it.
    "0.828": "the ceiling in the war story, recorded as history",
    "0.850": "the impossible recall in the war story, recorded as history",
}


def load_metrics() -> tuple[dict[str, object], dict[str, list[str]], list[str]]:
    if not METRICS.is_file():
        raise SystemExit(
            f"{METRICS.relative_to(REPO)} is missing. Run tools/collect_metrics.py first."
        )
    payload = json.loads(METRICS.read_text(encoding="utf-8"))
    return payload["metrics"], payload["anchors"], payload["checked_documents"]


def policy_numbers() -> set[str]:
    """Every literal in the policy file, so a threshold in prose is not flagged."""
    if not POLICY.is_file():
        return set()
    raw = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            found.add(str(node))
            found.add(f"{float(node):g}")
            found.add(f"{100 * float(node):g}")

    walk(raw)
    return found


def rendered(value: object) -> list[str]:
    """Every string form a value may legitimately take in prose."""
    if isinstance(value, float):
        text = f"{value:g}"
        forms = {text, f"{value}"}
        if value == int(value):
            forms.add(str(int(value)))
        return sorted(forms)
    text = str(value)
    if isinstance(value, int) and value >= 1000:
        return sorted({text, f"{value:,}"})
    return [text]


def prose_of(path: Path) -> str:
    """The checkable prose of a document, with whitespace collapsed to one space.

    Collapsing whitespace is the structural fix for a trap that cost real time on
    an earlier build: an anchor phrase longer than a few words straddles a newline
    in wrapped markdown and then matches nothing, while the prose it guards is
    perfectly correct. Anchors are still kept short, but they no longer have to be
    lucky about where the line broke.
    """
    content = path.read_text(encoding="utf-8")
    for pattern in (FENCE, INLINE_CODE, HTML_ATTRIBUTE, LINK_TARGET):
        content = pattern.sub(" ", content)
    return WHITESPACE.sub(" ", content)


def forward_check(
    metrics: dict[str, object], anchors: dict[str, list[str]], documents: dict[str, str]
) -> list[str]:
    failures: list[str] = []
    for name, value in metrics.items():
        phrases = [template.format(form) for template in anchors[name] for form in rendered(value)]
        hits = [
            document
            for document, content in documents.items()
            if any(phrase in content for phrase in phrases)
        ]
        if not hits:
            failures.append(
                f"{name} = {value} appears in no checked document. Expected one of: "
                + "; ".join(f'"{phrase}"' for phrase in phrases[:4])
            )
    return failures


def reverse_check(metrics: dict[str, object], documents: dict[str, str]) -> dict[str, list[str]]:
    allowed = set(STRUCTURAL_NUMBERS) | policy_numbers()
    for value in metrics.values():
        allowed.update(rendered(value))
        if isinstance(value, float):
            allowed.add(str(int(value)) if value == int(value) else f"{value:g}")
    unexplained: dict[str, list[str]] = {}
    for document, content in documents.items():
        found = sorted({match.group(0) for match in NUMBER.finditer(content)})
        leftovers = [
            token
            for token in found
            if token not in allowed and token.replace(",", "") not in allowed
        ]
        if leftovers:
            unexplained[document] = leftovers
    return unexplained


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true", help="also fail on an unexplained number in prose"
    )
    parser.add_argument("--summary", help="append a markdown summary to this file")
    args = parser.parse_args(argv)

    metrics, anchors, checked = load_metrics()
    documents: dict[str, str] = {}
    for name in checked:
        path = REPO / name
        if not path.is_file():
            print(f"missing checked document: {name}", file=sys.stderr)
            return 2
        documents[name] = prose_of(path)

    failures = forward_check(metrics, anchors, documents)
    unexplained = reverse_check(metrics, documents)

    print(f"checked {len(metrics)} metrics against {len(documents)} documents")
    for failure in failures:
        print(f"STALE  {failure}")
    for document, tokens in unexplained.items():
        print(f"UNANCHORED  {document}: {', '.join(tokens)}")

    if args.summary:
        lines = [
            "### Receipts",
            "",
            f"- metrics re-measured: {len(metrics)}",
            f"- documents checked: {len(documents)}",
            f"- stale figures: {len(failures)}",
            f"- unanchored numbers in prose: {sum(len(v) for v in unexplained.values())}",
            "",
        ]
        if failures:
            lines += ["Stale figures:", ""] + [f"- {item}" for item in failures] + [""]
        if unexplained:
            lines += (
                ["Unanchored numbers:", ""]
                + [
                    f"- `{document}`: {', '.join(tokens)}"
                    for document, tokens in unexplained.items()
                ]
                + [""]
            )
        with Path(args.summary).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

    if failures:
        print(f"{len(failures)} figures no longer match the code", file=sys.stderr)
        return 1
    if args.strict and unexplained:
        print("unexplained numbers in prose, and --strict was given", file=sys.stderr)
        return 1
    print("every published figure matches the code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
