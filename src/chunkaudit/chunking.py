"""The chunkers, and the one property they are all measured on.

A chunker is a function from a document to a tuple of spans. Nothing here knows
about embeddings or questions, which is deliberate: the central claim of this
repository is that a chunker's damage is decidable before any retrieval happens,
and keeping the two modules apart is what makes that claim checkable rather than
asserted.

Four strategies, chosen so the comparison says something. Fixed character windows
are what most pipelines ship. Sentence windows are what most pipelines move to
when the fixed ones cut a sentence in half. Recursive splitting is the documented
behaviour of the splitter people reach for first, reimplemented here so the
package has no runtime dependency on it and so the behaviour being measured is
stated rather than imported. Whole document chunks are the trivial upper bound,
included because they make the trade off visible: their containment ceiling is
perfect and they retrieve badly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .documents import Document, Span
from .errors import UnanswerableError, UsageError

RECURSIVE_SEPARATORS = (". ", "; ", ", ", " ")


@dataclass(frozen=True)
class Chunk:
    """One chunk: which document, which position in the chunking, which characters."""

    doc_id: str
    index: int
    span: Span

    @property
    def key(self) -> str:
        return f"{self.doc_id}#{self.index}"


@dataclass(frozen=True)
class Chunking:
    """A named strategy with its parameters, and the chunks it produced.

    The parameters travel with the chunks because every published figure is
    conditional on them. A ceiling of 0.94 means nothing without the size and
    stride that produced it.
    """

    strategy: str
    size: int
    stride: int
    chunks: tuple[Chunk, ...]

    @property
    def name(self) -> str:
        if self.strategy == "document":
            return "document"
        return f"{self.strategy}-{self.size}-{self.stride}"

    @property
    def overlap(self) -> int:
        """Characters or sentences shared between consecutive chunks.

        The quantity that turns out to be a hard guarantee threshold on answer
        length rather than a tuning knob. See ADR-001.
        """
        return max(0, self.size - self.stride)

    @property
    def count(self) -> int:
        return len(self.chunks)

    def by_document(self) -> dict[str, tuple[Chunk, ...]]:
        grouped: dict[str, list[Chunk]] = {}
        for chunk in self.chunks:
            grouped.setdefault(chunk.doc_id, []).append(chunk)
        return {key: tuple(value) for key, value in grouped.items()}


def fixed_spans(length: int, size: int, stride: int) -> tuple[Span, ...]:
    """Character windows of `size`, advanced by `stride`.

    The tail is kept rather than dropped, and it is the reason the ceiling is
    computed by enumeration as well as in closed form: the last window is short,
    so a span near the end of a document has fewer chances to be contained than
    the closed form for an infinite document would suggest.
    """
    if size < 1:
        raise UsageError(f"chunk size must be at least 1, got {size}")
    if stride < 1:
        raise UsageError(f"chunk stride must be at least 1, got {stride}")
    if stride > size:
        raise UsageError(
            f"a stride of {stride} exceeds a size of {size}, which would skip characters "
            "entirely and make the corpus partly unreachable"
        )
    spans: list[Span] = []
    start = 0
    while start < length:
        end = min(start + size, length)
        spans.append(Span(start, end))
        if end == length:
            break
        start += stride
    return tuple(spans)


def sentence_spans(sentences: tuple[Span, ...], window: int, stride: int) -> tuple[Span, ...]:
    """Windows of `window` consecutive sentences, advanced by `stride` sentences."""
    if window < 1:
        raise UsageError(f"sentence window must be at least 1, got {window}")
    if stride < 1:
        raise UsageError(f"sentence stride must be at least 1, got {stride}")
    if stride > window:
        raise UsageError(
            f"a sentence stride of {stride} exceeds a window of {window}, which would skip "
            "sentences entirely"
        )
    if not sentences:
        raise UnanswerableError("a document with no sentence boundaries cannot be windowed")
    spans: list[Span] = []
    index = 0
    while index < len(sentences):
        last = min(index + window, len(sentences)) - 1
        spans.append(Span(sentences[index].start, sentences[last].end))
        if last == len(sentences) - 1:
            break
        index += stride
    return tuple(spans)


def recursive_spans(text: str, size: int, overlap: int) -> tuple[Span, ...]:
    """Split at the coarsest separator that fits, then merge back up to `size`.

    A reimplementation of the documented recursive splitting behaviour, not a
    port of anybody's code. The behaviour it reproduces: try the separators in
    order, take the first that yields pieces smaller than the target, then glue
    consecutive pieces together until adding one more would exceed the target,
    carrying `overlap` characters from the end of each chunk into the next.

    Written out here for one reason. The whole repository is about what a chunker
    destroys, so a chunker whose behaviour is a dependency's implementation detail
    would make every figure a statement about a version number.
    """
    if size < 1:
        raise UsageError(f"chunk size must be at least 1, got {size}")
    if overlap < 0:
        raise UsageError(f"overlap cannot be negative, got {overlap}")
    if overlap >= size:
        raise UsageError(
            f"an overlap of {overlap} is not smaller than a size of {size}, which would "
            "advance by nothing and never terminate"
        )
    pieces = _split_recursive(text, 0, size, RECURSIVE_SEPARATORS)
    spans: list[Span] = []
    current_start = 0
    current_end = 0
    for piece in pieces:
        if current_end == 0:
            current_start, current_end = piece.start, piece.end
            continue
        if piece.end - current_start <= size:
            current_end = piece.end
            continue
        spans.append(Span(current_start, current_end))
        current_start = max(current_end - overlap, piece.start) if overlap else piece.start
        current_end = piece.end
    if current_end > current_start:
        spans.append(Span(current_start, current_end))
    return tuple(spans)


def _split_recursive(
    text: str, offset: int, size: int, separators: tuple[str, ...]
) -> tuple[Span, ...]:
    if len(text) <= size or not separators:
        return (Span(offset, offset + len(text)),) if text else ()
    separator = separators[0]
    if separator not in text:
        return _split_recursive(text, offset, size, separators[1:])
    pieces: list[Span] = []
    cursor = 0
    while True:
        found = text.find(separator, cursor)
        if found == -1:
            break
        end = found + len(separator)
        if end > cursor:
            pieces.extend(_split_recursive(text[cursor:end], offset + cursor, size, separators[1:]))
        cursor = end
    if cursor < len(text):
        pieces.extend(_split_recursive(text[cursor:], offset + cursor, size, separators[1:]))
    return tuple(pieces)


def chunk_document(document: Document, strategy: str, size: int, stride: int) -> tuple[Span, ...]:
    if strategy == "fixed":
        return fixed_spans(document.length, size, stride)
    if strategy == "sentence":
        return sentence_spans(document.sentences, size, stride)
    if strategy == "recursive":
        return recursive_spans(document.text, size, size - stride)
    if strategy == "document":
        return (Span(0, document.length),)
    raise UsageError(
        f"unknown chunking strategy {strategy!r}, expected one of "
        "fixed, sentence, recursive, document"
    )


def build_chunking(
    documents: tuple[Document, ...], strategy: str, size: int = 1, stride: int = 1
) -> Chunking:
    """Chunk every document and return the whole chunking as one object."""
    chunks: list[Chunk] = []
    for document in documents:
        spans = chunk_document(document, strategy, size, stride)
        if not spans and document.length:
            raise UnanswerableError(
                f"strategy {strategy!r} produced no chunks for {document.doc_id}, which has "
                f"{document.length} characters. An audit of an empty chunking is not an audit"
            )
        for index, span in enumerate(spans):
            chunks.append(Chunk(doc_id=document.doc_id, index=index, span=span))
    return Chunking(strategy=strategy, size=size, stride=stride, chunks=tuple(chunks))


PLAN: tuple[tuple[str, int, int], ...] = (
    ("fixed", 200, 200),
    ("fixed", 200, 150),
    ("fixed", 400, 400),
    ("fixed", 400, 300),
    ("fixed", 400, 200),
    ("fixed", 800, 800),
    ("fixed", 800, 600),
    ("sentence", 1, 1),
    ("sentence", 2, 1),
    ("sentence", 3, 2),
    ("recursive", 400, 300),
    ("recursive", 800, 600),
    ("document", 1, 1),
)
