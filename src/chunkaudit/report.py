"""Rendering an audit and a sweep, as text and as HTML.

The HTML report is what `tools/capture_screenshots.py` photographs, and its job
is to put the ceiling, the standard recall and the span complete recall on one
screen so a reader sees the gap rather than a verdict.

The markup is f strings with `html.escape`, so the report is one self contained
file with no template directory to keep in step with the code, and escaping is
the author's job. A test asserts that a hostile chunking name comes out inert.
The palette is fixed rather than inherited so a screenshot is legible in any
theme, and every class in the markup is listed in STYLED_CLASSES with a test
asserting each has a rule: on two earlier projects a badge class and a table cell
class collided at equal specificity and a verdict rendered green on green while
every test passed.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from .audit import AuditResult, Verdict
from .pipeline import AuditRow

VERDICT_TEXT = {
    Verdict.SURVIVES: "Answers survive this chunker",
    Verdict.DESTROYING: "This chunker destroys material answers",
    Verdict.UNATTRIBUTABLE: "The causes cannot be told apart, a human is needed",
}

VERDICT_CLASS = {
    Verdict.SURVIVES: "badge-clear",
    Verdict.DESTROYING: "badge-alarm",
    Verdict.UNATTRIBUTABLE: "badge-unknown",
}

STYLED_CLASSES = (
    "page",
    "masthead",
    "subtitle",
    "badge",
    "badge-clear",
    "badge-alarm",
    "badge-unknown",
    "tiles",
    "tile",
    "tile-label",
    "tile-value",
    "tile-note",
    "section",
    "grid",
    "numeric",
    "bad",
    "good",
    "ceilingrow",
    "footnote",
    "bar",
    "bar-fill",
    "bar-ceiling",
)

STYLESHEET = """
:root { color-scheme: only light; }
body { margin: 0; background: #f4f5f7; color: #14171a;
       font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.page { max-width: 1000px; margin: 0 auto; padding: 32px 28px 56px; background: #ffffff; }
.masthead { font-size: 26px; font-weight: 650; letter-spacing: -0.2px; margin: 0 0 4px; }
.subtitle { color: #4a5159; font-size: 14px; margin: 0 0 22px; }
.badge { display: inline-block; padding: 5px 12px; border-radius: 4px; font-size: 13px;
         font-weight: 650; border: 1px solid transparent; }
.badge-clear { background: #e4f2e6; color: #16491f; border-color: #a9d4b0; }
.badge-alarm { background: #fae3e3; color: #6d1717; border-color: #e0a7a7; }
.badge-unknown { background: #fdf0d8; color: #6a4708; border-color: #e5c583; }
.tiles { display: flex; flex-wrap: wrap; gap: 12px; margin: 20px 0 26px; }
.tile { flex: 1 1 195px; border: 1px solid #dcdfe3; border-radius: 6px; padding: 12px 14px;
        background: #fbfbfc; }
.tile-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.7px; color: #5b636b; }
.tile-value { font-size: 23px; font-weight: 650; margin-top: 4px;
              font-variant-numeric: tabular-nums; }
.tile-note { font-size: 12px; color: #5b636b; margin-top: 3px; }
.section { margin: 30px 0 0; }
.section h2 { font-size: 16px; margin: 0 0 4px; }
.section p { font-size: 13.5px; color: #3c4349; margin: 0 0 12px; max-width: 72ch; }
.grid { width: 100%; border-collapse: collapse; font-size: 13px; }
.grid th, .grid td { border-bottom: 1px solid #e6e8eb; padding: 7px 9px; text-align: left; }
.grid th { background: #f0f1f3; font-weight: 600; font-size: 11.5px; text-transform: uppercase;
           letter-spacing: 0.5px; color: #40474e; }
.grid td.numeric { text-align: right; font-variant-numeric: tabular-nums; }
.grid td.bad { color: #6d1717; font-weight: 650; }
.grid td.good { color: #16491f; font-weight: 650; }
.grid tr.ceilingrow td { background: #eef4ea; font-weight: 650; }
.footnote { font-size: 12px; color: #5b636b; margin-top: 10px; max-width: 80ch; }
.bar { position: relative; height: 14px; width: 220px; background: #e6e8eb; border-radius: 3px;
       overflow: hidden; }
.bar-fill { position: absolute; left: 0; top: 0; bottom: 0; background: #4c6b8a; }
.bar-ceiling { position: absolute; top: -2px; bottom: -2px; width: 2px; background: #6d1717; }
"""


def _pct(value: float) -> str:
    return "n/a" if value != value else f"{100.0 * value:.1f}%"


def _bar(value: float, ceiling: float) -> str:
    """A filled bar with the ceiling marked, because the ceiling is the point.

    The mark is what makes the picture say something a number does not: the
    distance from the fill to the mark is what a retriever could still win, and
    everything to the right of the mark is not available to anybody.
    """
    fill = max(0.0, min(1.0, value)) * 100.0
    mark = max(0.0, min(1.0, ceiling)) * 100.0
    return (
        f'<div class="bar"><div class="bar-fill" style="width:{fill:.1f}%"></div>'
        f'<div class="bar-ceiling" style="left:{mark:.1f}%"></div></div>'
    )


def render_text(result: AuditResult) -> str:
    """The CLI's report. The ceiling is printed before any retrieval number."""
    metrics = result.metrics
    ceiling = result.ceiling
    lines: list[str] = []
    lines.append(f"verdict: {result.verdict.value}")
    lines.append(
        f"chunking: {ceiling.chunking}  strategy: {ceiling.strategy}  "
        f"size: {ceiling.size}  stride: {ceiling.stride}  overlap: {ceiling.overlap}"
    )
    lines.append(f"chunks: {ceiling.chunk_count}  questions: {ceiling.questions}")
    lines.append("")
    lines.append("decided before any retrieval ran")
    guaranteed = ceiling.guaranteed_length
    lines.append(
        "  longest answer guaranteed to survive at any position: "
        + (f"{guaranteed} characters" if guaranteed is not None else "not a single number")
    )
    lines.append(
        f"  containment ceiling: {ceiling.ceiling:.4f} "
        f"({ceiling.questions - ceiling.destroyed} of {ceiling.questions} answers survive)"
    )
    for band, (contained, total) in ceiling.ceiling_by_band().items():
        lines.append(f"    answers targeting {band} characters: {contained} of {total} survive")
    lines.append("")
    lines.append(f"measured with {metrics.retriever} at k={metrics.k}")
    lines.append(f"  chunk level recall, the standard metric: {metrics.chunk_recall.value:.4f}")
    lines.append(
        f"  span complete recall                  : {metrics.span_complete_recall.value:.4f}"
    )
    lines.append(f"  the gap between them                  : {metrics.gap:.4f}")
    lines.append(
        f"  assembled recall, if pieces are stitched: {metrics.assembled_recall.value:.4f}"
    )
    lines.append(
        f"  questions the standard metric counts as hits that cannot answer alone: "
        f"{metrics.overstated.numerator} of {metrics.overstated.denominator}"
    )
    lines.append("")
    lines.append("why each failure happened")
    for cause, count in metrics.causes.items():
        if count:
            lines.append(f"  {cause:<24}{count:>5}")
    fixable = metrics.fixable_by_retriever
    lines.append(
        f"  of {fixable.denominator} failures, {fixable.numerator} could be fixed by a "
        "better retriever"
    )
    lines.append(
        f"  headroom a perfect retriever would recover: {result.headroom:.4f} "
        f"({_pct(result.attainable_share)} of the shortfall)"
    )
    return "\n".join(lines) + "\n"


def _tile(label: str, value: str, note: str) -> str:
    return (
        '<div class="tile">'
        f'<div class="tile-label">{escape(label)}</div>'
        f'<div class="tile-value">{escape(value)}</div>'
        f'<div class="tile-note">{escape(note)}</div>'
        "</div>"
    )


def render_html(result: AuditResult) -> str:
    metrics = result.metrics
    ceiling = result.ceiling
    guaranteed = ceiling.guaranteed_length
    tiles = [
        _tile(
            "containment ceiling",
            f"{ceiling.ceiling:.4f}",
            "decided before any retrieval ran",
        ),
        _tile(
            "chunk level recall",
            f"{metrics.chunk_recall.value:.4f}",
            "the standard metric, under its real name",
        ),
        _tile(
            "span complete recall",
            f"{metrics.span_complete_recall.value:.4f}",
            "a single chunk holding the whole answer",
        ),
        _tile(
            "hits that cannot answer alone",
            f"{metrics.overstated.numerator} of {metrics.overstated.denominator}",
            "counted as successes by the standard metric",
        ),
    ]
    band_rows = "".join(
        "<tr>"
        f"<td>answers targeting {band} characters</td>"
        f'<td class="numeric">{contained}</td>'
        f'<td class="numeric">{total}</td>'
        f'<td class="numeric {"good" if contained == total else "bad"}">'
        f"{_pct(contained / total)}</td>"
        "</tr>"
        for band, (contained, total) in ceiling.ceiling_by_band().items()
    )
    cause_rows = "".join(
        "<tr>"
        f"<td>{escape(cause)}</td>"
        f'<td class="numeric">{count}</td>'
        f'<td class="numeric">{_pct(count / metrics.questions)}</td>'
        "</tr>"
        for cause, count in metrics.causes.items()
        if count
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>chunkaudit</title>
<style>{STYLESHEET}</style>
</head><body><div class="page">
<h1 class="masthead">What this chunker destroyed</h1>
<p class="subtitle">{escape(ceiling.chunking)}, {ceiling.chunk_count} chunks,
measured with {escape(metrics.retriever)} at k={metrics.k} over
{ceiling.questions} questions</p>
<span class="badge {VERDICT_CLASS[result.verdict]}">
{escape(VERDICT_TEXT[result.verdict])}</span>
<div class="tiles">{"".join(tiles)}</div>
<div class="section"><h2>Decided before any retrieval ran</h2>
<p>Whether a chunk holds an answer whole is a question about character offsets, so
it has an exact answer and no model is involved. The longest answer this chunking
preserves at every position is
{f"{guaranteed} characters" if guaranteed is not None else "not a single number for this strategy"}.
No retriever can exceed the ceiling, because a retriever cannot return a chunk
that was never made.</p>
<table class="grid"><thead><tr><th>answer length band</th><th>survived</th>
<th>total</th><th>share</th></tr></thead><tbody>{band_rows}
<tr class="ceilingrow"><td>containment ceiling</td>
<td class="numeric">{ceiling.questions - ceiling.destroyed}</td>
<td class="numeric">{ceiling.questions}</td>
<td class="numeric">{_pct(ceiling.ceiling)}</td></tr></tbody></table></div>
<div class="section"><h2>The standard metric against the one a reader assumes</h2>
<p>The bar shows the measured span complete recall. The dark mark is the ceiling.
Everything between the fill and the mark is what a better retriever could still
win, and everything to the right of the mark is not available to anyone.</p>
<table class="grid"><thead><tr><th>measure</th><th>value</th><th></th></tr></thead>
<tbody>
<tr><td>chunk level recall, the standard metric</td>
<td class="numeric">{metrics.chunk_recall.value:.4f}</td>
<td>{_bar(metrics.chunk_recall.value, ceiling.ceiling)}</td></tr>
<tr><td>assembled recall, if the pieces are stitched</td>
<td class="numeric">{metrics.assembled_recall.value:.4f}</td>
<td>{_bar(metrics.assembled_recall.value, ceiling.ceiling)}</td></tr>
<tr><td>span complete recall</td>
<td class="numeric">{metrics.span_complete_recall.value:.4f}</td>
<td>{_bar(metrics.span_complete_recall.value, ceiling.ceiling)}</td></tr>
<tr><td>the gap between the first and the last</td>
<td class="numeric bad">{metrics.gap:.4f}</td><td></td></tr>
</tbody></table></div>
<div class="section"><h2>Why each failure happened</h2>
<p>Exactly one cause applies to each question, and only one of them can be fixed
by touching the retriever. Of {metrics.fixable_by_retriever.denominator} failures,
{metrics.fixable_by_retriever.numerator} could be.</p>
<table class="grid"><thead><tr><th>cause</th><th>questions</th>
<th>share</th></tr></thead><tbody>{cause_rows}</tbody></table>
<p class="footnote">The median failure had
{_pct(metrics.median_retrieved_share)} of its answer somewhere in the retrieved
chunks, which is the difference between a chunker that lost a clause and one that
lost the answer.</p></div>
</div></body></html>
"""


def render_sweep_html(rows: Sequence[AuditRow], *, retriever: str, k: int) -> str:
    """The whole sweep as one page, narrowed to one retriever and one k."""
    selected = [row for row in rows if row.retriever == retriever and row.k == k]
    if not selected:
        raise ValueError(f"no rows for retriever {retriever!r} at k={k}")
    ordered = sorted(selected, key=lambda row: row.ceiling)
    worst = ordered[0]
    body = "".join(
        "<tr>"
        f"<td>{escape(row.chunking)}</td>"
        f'<td class="numeric">{row.chunk_count}</td>'
        f'<td class="numeric">{row.overlap}</td>'
        f'<td class="numeric">'
        f"{row.guaranteed_length if row.guaranteed_length is not None else 'n/a'}</td>"
        f'<td class="numeric">{row.ceiling:.4f}</td>'
        f'<td class="numeric">{row.chunk_recall:.4f}</td>'
        f'<td class="numeric">{row.span_complete_recall:.4f}</td>'
        f'<td class="numeric {"bad" if row.gap >= 0.02 else "good"}">{row.gap:.4f}</td>'
        f'<td class="numeric">{row.destroyed_by_chunking}</td>'
        f'<td class="numeric">{row.missed_by_retrieval}</td>'
        "</tr>"
        for row in ordered
    )
    tiles = [
        _tile("chunkings audited", str(len(ordered)), "every one at the same k"),
        _tile(
            "worst ceiling",
            f"{worst.ceiling:.4f}",
            f"{escape(worst.chunking)}, before retrieval",
        ),
        _tile(
            "largest gap",
            f"{max(row.gap for row in ordered):.4f}",
            "standard metric minus span complete",
        ),
        _tile(
            "failures a retriever could fix",
            _pct(
                sum(row.missed_by_retrieval for row in ordered)
                / max(
                    1, sum(row.missed_by_retrieval + row.destroyed_by_chunking for row in ordered)
                )
            ),
            "across every chunking here",
        ),
    ]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>chunkaudit sweep</title>
<style>{STYLESHEET}</style>
</head><body><div class="page">
<h1 class="masthead">Every chunking, and what each one costs before retrieval</h1>
<p class="subtitle">Measured with {escape(retriever)} at k={k}. Sorted by ceiling,
worst first.</p>
<span class="badge badge-alarm">The gap column is the point</span>
<div class="tiles">{"".join(tiles)}</div>
<div class="section"><h2>The ceiling is a property of the chunker</h2>
<p>The guaranteed column is the longest answer the chunking preserves wherever it
sits, which for uniform character windows is the overlap plus one. Above that
length, survival depends on where the answer happens to fall, and the ceiling
column is the measured rate rather than the bound.</p>
<table class="grid"><thead><tr><th>chunking</th><th>chunks</th><th>overlap</th>
<th>guaranteed</th><th>ceiling</th><th>chunk recall</th><th>span complete</th>
<th>gap</th><th>destroyed</th><th>missed</th></tr></thead>
<tbody>{body}</tbody></table>
<p class="footnote">Destroyed and missed are counts of questions. Destroyed means
no chunk anywhere held the answer whole, which no retriever change can address.
Missed means one existed and was not retrieved, which is the only column an
embedding upgrade touches.</p></div>
</div></body></html>
"""
