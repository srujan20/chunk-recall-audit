"""Render the architecture diagram to a committed SVG.

Written by hand rather than through a diagramming library, for four reasons that
each cost time on other projects.

GitHub's lazily loaded Mermaid renderer sometimes reports "Unable to render rich
display" for a diagram that parses correctly everywhere else. There is nothing to
fix in the source and no way to fix it from the repository, so the diagram is
committed as an image instead.

A diagram with HTML labels is not well formed XML, because the labels end up
inside a foreignObject with unclosed br tags. It displays when injected into a
live page and fails silently as an img src, with naturalWidth 0 and nothing in
any console. This file emits text and tspan only.

An img src needs intrinsic dimensions. A percentage width with no height leaves a
browser without an aspect ratio and it picks a default.

A transparent background is not theme neutral. Node fills are light with dark
text either way, so an unfilled label comes out dark grey on near black in a dark
theme. One opaque rectangle covers the whole viewBox.

Usage:
    python tools/render_diagram.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "docs" / "diagrams" / "architecture.svg"
MANIFEST = REPO / "docs" / "diagrams" / "manifest.json"

WIDTH = 1000
HEIGHT = 744
FONT = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

INK = "#14171a"
MUTED = "#5b636b"
LINE = "#9aa2aa"
PAPER = "#ffffff"
PANEL = "#f2f4f6"
FREE_FILL = "#eef4ea"
FREE_EDGE = "#b3cba4"
COST_FILL = "#e8eef5"
COST_EDGE = "#a9bed4"
BLIND_FILL = "#fdf0d8"
BLIND_EDGE = "#e5c583"
METHOD_FILL = "#ffffff"
METHOD_EDGE = "#8f9aa4"


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int
    title: str
    lines: tuple[str, ...] = ()
    fill: str = METHOD_FILL
    edge: str = METHOD_EDGE
    mono: bool = False

    @property
    def centre_x(self) -> int:
        return self.x + self.width // 2

    @property
    def bottom(self) -> int:
        return self.y + self.height


CORPUS = Box(
    40,
    64,
    440,
    100,
    "The corpus: documents and answer spans",
    (
        "an answer is a half open character interval",
        "into one named document, so containment is",
        "an interval question with an exact answer",
    ),
    fill=PANEL,
    edge=METHOD_EDGE,
)

CHUNKER = Box(
    520,
    64,
    440,
    100,
    "The chunking: size, stride, strategy",
    (
        "four strategies, one of them a reimplemented",
        "recursive splitter, so the behaviour measured",
        "is written down here rather than imported",
    ),
    fill=PANEL,
    edge=METHOD_EDGE,
)

CEILING = Box(
    40,
    212,
    920,
    108,
    "The containment ceiling, computed with no model at all",
    (
        "Does any chunk hold this answer whole? Interval arithmetic, exact, and cheap"
        " enough that the whole sweep",
        "finishes in seconds. The aggregate is the highest span complete recall any"
        " retriever can reach, and an",
        "oracle attains it, so the bound is tight rather than merely an upper one.",
    ),
    fill=FREE_FILL,
    edge=FREE_EDGE,
)

RETRIEVERS = (
    Box(
        40,
        366,
        222,
        96,
        "bm25",
        ("Okapi, written out", "the parameters are", "part of the finding"),
    ),
    Box(
        278,
        366,
        222,
        96,
        "hashed vectors",
        ("character n grams with", "idf weighting. A lexical", "method, not a neural one"),
    ),
    Box(
        516,
        366,
        222,
        96,
        "oracle",
        ("sees the answer", "an upper bound", "attains the ceiling"),
    ),
    Box(
        754,
        366,
        206,
        96,
        "sentence transformer",
        ("written, never run", "the weights host was", "unreachable. ADR-003"),
        fill=BLIND_FILL,
        edge=BLIND_EDGE,
    ),
)

CAUSES = Box(
    40,
    496,
    920,
    84,
    "Every failure, attributed to exactly one cause",
    (
        "no chunk holds it whole, which no retriever change reaches  |  a chunk holds it"
        " and was not retrieved,",
        "which is the only one an encoder upgrade touches  |  it is not in the corpus at all",
    ),
    fill=COST_FILL,
    edge=COST_EDGE,
)

VERDICT = Box(
    250,
    608,
    500,
    96,
    "Verdict, and the exit code that carries it",
    (
        "0  the answers survive this chunking",
        "1  the chunker destroys material answers",
        "2  the causes cannot be told apart",
    ),
    fill=PANEL,
    edge=METHOD_EDGE,
    mono=True,
)


def element(parent: ElementTree.Element, tag: str, **attributes: object) -> ElementTree.Element:
    return ElementTree.SubElement(
        parent, tag, {key.replace("_", "-"): str(value) for key, value in attributes.items()}
    )


def text(
    parent: ElementTree.Element,
    x: int,
    y: int,
    content: str,
    *,
    size: float = 13,
    weight: str = "400",
    fill: str = INK,
    anchor: str = "start",
    family: str = FONT,
) -> None:
    node = element(
        parent,
        "text",
        x=x,
        y=y,
        fill=fill,
        font_size=size,
        font_weight=weight,
        font_family=family,
        text_anchor=anchor,
    )
    span = ElementTree.SubElement(node, "tspan")
    span.text = content


def draw_box(parent: ElementTree.Element, box: Box) -> None:
    element(
        parent,
        "rect",
        x=box.x,
        y=box.y,
        width=box.width,
        height=box.height,
        rx=6,
        fill=box.fill,
        stroke=box.edge,
        stroke_width=1.2,
    )
    text(parent, box.x + 14, box.y + 25, box.title, size=13.5, weight="650")
    for index, line in enumerate(box.lines):
        text(
            parent,
            box.x + 14,
            box.y + 46 + index * (17 if box.mono else 19),
            line,
            size=11.5,
            fill=MUTED,
            family=MONO if box.mono else FONT,
        )


def draw_arrow(parent: ElementTree.Element, x1: int, y1: int, x2: int, y2: int) -> None:
    element(
        parent,
        "line",
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        stroke=LINE,
        stroke_width=1.2,
        marker_end="url(#arrow)",
    )


def build() -> ElementTree.Element:
    svg = ElementTree.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "viewBox": f"0 0 {WIDTH} {HEIGHT}",
            "width": str(WIDTH),
            "height": str(HEIGHT),
            "role": "img",
            "aria-label": (
                "What the chunker decides before retrieval, what the retriever decides "
                "after, and which failures belong to which"
            ),
        },
    )
    defs = element(svg, "defs")
    marker = element(
        defs,
        "marker",
        id="arrow",
        viewBox="0 0 10 10",
        refX=9,
        refY=5,
        markerWidth=7,
        markerHeight=7,
        orient="auto-start-reverse",
    )
    element(marker, "path", d="M 0 0 L 10 5 L 0 10 z", fill=LINE)

    element(svg, "rect", x=0, y=0, width=WIDTH, height=HEIGHT, fill=PAPER)

    text(
        svg,
        40,
        32,
        "chunkaudit: the bound is decided above the line, and every retriever lives below it",
        size=15,
        weight="650",
    )

    draw_box(svg, CORPUS)
    draw_box(svg, CHUNKER)
    draw_arrow(svg, CORPUS.centre_x, CORPUS.bottom + 2, CORPUS.centre_x, CEILING.y - 4)
    draw_arrow(svg, CHUNKER.centre_x, CHUNKER.bottom + 2, CHUNKER.centre_x, CEILING.y - 4)
    draw_box(svg, CEILING)

    # The dividing line. Everything above it costs nothing and bounds everything
    # below it, which is the one idea the picture exists to carry.
    element(
        svg,
        "line",
        x1=24,
        y1=344,
        x2=WIDTH - 24,
        y2=344,
        stroke="#6d1717",
        stroke_width=1.4,
        stroke_dasharray="7 5",
    )
    text(svg, 28, 338, "free, exact, bounds everything below", size=11, fill="#6d1717")
    text(
        svg,
        WIDTH - 28,
        338,
        "needs an index, and cannot exceed the line",
        size=11,
        fill="#6d1717",
        anchor="end",
    )

    for box in RETRIEVERS:
        draw_arrow(svg, box.centre_x, box.y - 22, box.centre_x, box.y - 4)
        draw_box(svg, box)
        draw_arrow(svg, box.centre_x, box.bottom + 2, box.centre_x, CAUSES.y - 4)
    draw_box(svg, CAUSES)
    draw_arrow(svg, CAUSES.centre_x, CAUSES.bottom + 2, VERDICT.centre_x, VERDICT.y - 4)
    draw_box(svg, VERDICT)
    text(
        svg,
        40,
        HEIGHT - 10,
        "The amber box is a retriever this build could not run. The green box bounds it "
        "anyway, which is the point.",
        size=11.5,
        fill=MUTED,
    )
    return svg


def main() -> int:
    svg = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ElementTree.indent(svg, space="  ")
    payload = ElementTree.tostring(svg, encoding="unicode", xml_declaration=False)
    OUTPUT.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + payload + "\n", encoding="utf-8")

    # Parsing the file back is the check that matters: an img src silently fails
    # to load a document that is not well formed, with nothing in any console.
    ElementTree.parse(OUTPUT)
    MANIFEST.write_text(
        json.dumps(
            {
                "file": str(OUTPUT.relative_to(REPO)),
                "width": WIDTH,
                "height": HEIGHT,
                "generated_by": "tools/render_diagram.py",
                "labels": "text and tspan only, no foreignObject",
                "background": "one opaque rectangle covering the whole viewBox",
                "boxes": len(RETRIEVERS) + 4,
                "bytes": OUTPUT.stat().st_size,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT.relative_to(REPO)} ({OUTPUT.stat().st_size} bytes, {WIDTH}x{HEIGHT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
