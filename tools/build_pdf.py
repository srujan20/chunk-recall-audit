"""Lay out a markdown document as a PDF for offline reading.

Rendered with cmark-gfm, which is the library GitHub uses, so the tables and
fenced blocks come out the way they do on the repository page. Laid out by
Chromium through page.pdf(), because it is the only engine here that paginates
tables without breaking a row across a page.

House rules applied: plain black text, a ten point body, no decorative colour, no
cover page for the copy that lives in the repository, and a cover page carrying
this project's figures for the copy that is handed over.

Usage:
    python tools/build_pdf.py docs/defense-guide.md [--out PATH] [--cover]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cmarkgfm
from cmarkgfm.cmark import Options
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
SCRATCH = REPO / ".cache"

STYLE = """
@page { size: A4; margin: 18mm 16mm 16mm 16mm; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       font-size: 10pt; line-height: 1.45; color: #000000; margin: 0; }
h1 { font-size: 17pt; margin: 0 0 8pt; }
h2 { font-size: 13pt; margin: 16pt 0 5pt; border-bottom: 0.6pt solid #000000;
     padding-bottom: 3pt; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; page-break-after: avoid; }
p, li { font-size: 10pt; }
ul, ol { margin: 5pt 0 5pt 16pt; padding: 0; }
li { margin: 2pt 0; }
strong { font-weight: 650; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
       font-size: 8.8pt; }
pre { font-size: 8.6pt; line-height: 1.35; border: 0.5pt solid #000000; padding: 6pt;
      white-space: pre-wrap; page-break-inside: avoid; margin: 6pt 0; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: 6pt 0;
        page-break-inside: avoid; }
th, td { border: 0.5pt solid #000000; padding: 3pt 5pt; text-align: left;
         vertical-align: top; }
th { font-weight: 650; }
tr { page-break-inside: avoid; }
blockquote { margin: 6pt 0 6pt 10pt; padding-left: 8pt; border-left: 1pt solid #000000; }
.cover { page-break-after: always; }
.cover h1 { font-size: 22pt; margin: 0 0 2pt; }
.cover .subject { font-size: 11pt; margin: 0 0 18pt; }
.cover table { width: 100%; font-size: 9.5pt; }
.cover .note { font-size: 9pt; margin-top: 14pt; }
"""

FOOTER = (
    '<div style="width:100%;font-size:8pt;font-family:Helvetica,Arial,sans-serif;'
    'padding:0 16mm;display:flex;justify-content:space-between;color:#000;">'
    "<span>Srujan Sadineni  |  chunk-recall-audit</span>"
    '<span class="pageNumber"></span></div>'
)
HEADER = '<div style="font-size:0"></div>'

COVER_ROWS = (
    ("Containment ceiling on 200 character chunks", "default_200_ceiling", ""),
    ("The standard metric on the same rankings", "widest_gap_chunk_recall", ""),
    ("Widest gap between the two metrics", "widest_gap", ""),
    ("Hits counted as successes that cannot answer alone", "widest_gap_overstated", " of 360"),
    ("Failures across every chunking", "failures_total", ""),
    ("Of those, the chunker's", "failures_destroyed", ""),
    ("Of those, the retriever's", "failures_missed", ""),
    ("Chunkings with nothing a retriever could fix", "chunkings_nothing_fixable", " of 13"),
    ("Guarantee threshold at size 400, stride 300", "guarantee_at_400_300", " characters"),
    ("Positions checked at that length", "guarantee_verified_positions", ""),
    ("Range from changing the retriever", "retriever_range", ""),
    ("Range from changing the chunker", "chunker_range", ""),
    ("Oracle's worst distance from the ceiling", "ceiling_tightness", ""),
    ("Tests, all of them measured", "tests_total", ""),
    ("Line coverage", "coverage_line_pct", " percent"),
)


def cover_html() -> str:
    metrics = json.loads((REPO / "docs" / "metrics.json").read_text(encoding="utf-8"))["metrics"]
    rows = "".join(
        f"<tr><td>{label}</td><td style='text-align:right'>{metrics[key]}{suffix}</td></tr>"
        for label, key, suffix in COVER_ROWS
    )
    return f"""<div class="cover">
<h1>chunk-recall-audit</h1>
<p class="subject">Defense guide. A retrieval metric is computed on the chunks the
chunker produced, so it cannot see the answers the chunker destroyed. This is how
many of them there are, and who can fix them.</p>
<table><tbody>{rows}</tbody></table>
<p class="note">Every figure above is produced by code in the repository, re-measured
by CI on every push, and checked against the prose of this document by
tools/check_numbers.py. Reproduce all of it with one command: make verify.</p>
</div>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="markdown file to lay out")
    parser.add_argument("--out", help="output PDF path")
    parser.add_argument(
        "--cover", action="store_true", help="prepend a cover page carrying the figures"
    )
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_absolute():
        source = REPO / source
    if not source.is_file():
        raise SystemExit(f"{source} not found")
    destination = Path(args.out) if args.out else source.with_suffix(".pdf")

    body = cmarkgfm.markdown_to_html_with_extensions(
        source.read_text(encoding="utf-8"),
        options=Options.CMARK_OPT_UNSAFE,
        extensions=["table", "autolink", "strikethrough", "tagfilter"],
    )
    page_html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{STYLE}</style></head><body>"
        + (cover_html() if args.cover else "")
        + body
        + "</body></html>"
    )
    SCRATCH.mkdir(parents=True, exist_ok=True)
    scratch = SCRATCH / f"{source.stem}-print.html"
    scratch.write_text(page_html, encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(scratch.resolve().as_uri())
        page.wait_for_load_state("load")
        page.pdf(
            path=str(destination),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template=HEADER,
            footer_template=FOOTER,
            margin={"top": "18mm", "bottom": "16mm", "left": "0mm", "right": "0mm"},
        )
        browser.close()
    print(f"wrote {destination} ({destination.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
