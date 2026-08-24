"""The chunkers, and the ceiling arithmetic that is exact rather than measured."""

from __future__ import annotations

import pytest

from chunkaudit.ceiling import (
    ceiling_report,
    containment_for,
    guaranteed_length,
)
from chunkaudit.chunking import (
    PLAN,
    Chunk,
    Chunking,
    build_chunking,
    chunk_document,
    fixed_spans,
    recursive_spans,
    sentence_spans,
)
from chunkaudit.documents import Document, Question, Span
from chunkaudit.errors import UnanswerableError, UsageError


def test_fixed_windows_cover_the_document():
    spans = fixed_spans(1000, 400, 400)
    assert spans[0].start == 0
    assert spans[-1].end == 1000


def test_fixed_windows_keep_a_short_tail():
    """Dropping it would make the last characters of every document unreachable."""
    spans = fixed_spans(950, 400, 400)
    assert spans[-1].length == 150


def test_fixed_windows_advance_by_the_stride():
    spans = fixed_spans(1200, 400, 300)
    assert [span.start for span in spans[:3]] == [0, 300, 600]


def test_a_stride_larger_than_its_size_is_refused_with_the_reason():
    with pytest.raises(UsageError, match="partly unreachable"):
        fixed_spans(1000, 200, 400)


@pytest.mark.parametrize("size,stride", [(0, 1), (1, 0)])
def test_a_non_positive_size_or_stride_is_refused(size, stride):
    with pytest.raises(UsageError, match="at least 1"):
        fixed_spans(100, size, stride)


def test_sentence_windows_start_and_end_on_sentence_boundaries():
    sentences = (Span(0, 10), Span(11, 22), Span(23, 30))
    spans = sentence_spans(sentences, 2, 1)
    assert spans[0] == Span(0, 22)
    assert spans[-1].end == 30


def test_a_sentence_stride_larger_than_its_window_is_refused():
    with pytest.raises(UsageError, match="skip sentences"):
        sentence_spans((Span(0, 5), Span(6, 10)), 1, 2)


def test_windowing_a_document_with_no_sentences_is_unanswerable():
    with pytest.raises(UnanswerableError, match="no sentence boundaries"):
        sentence_spans((), 1, 1)


def test_recursive_splitting_prefers_the_coarsest_separator_that_fits():
    text = "First sentence here. Second sentence here. Third sentence here."
    spans = recursive_spans(text, 45, 0)
    pieces = [text[span.start : span.end] for span in spans]
    assert all(piece.strip().endswith(".") for piece in pieces)


def test_recursive_splitting_respects_the_target_size():
    text = " ".join(f"Sentence number {index} of the document." for index in range(20))
    for span in recursive_spans(text, 200, 0):
        assert span.length <= 200


def test_recursive_splitting_covers_the_text():
    text = " ".join(f"Sentence number {index} of the document." for index in range(12))
    spans = recursive_spans(text, 150, 0)
    assert spans[0].start == 0
    assert spans[-1].end == len(text)


def test_an_overlap_not_smaller_than_the_size_is_refused():
    with pytest.raises(UsageError, match="never terminate"):
        recursive_spans("some text here", 10, 10)


def test_a_negative_overlap_is_refused():
    with pytest.raises(UsageError, match="cannot be negative"):
        recursive_spans("some text here", 10, -1)


def test_the_document_strategy_makes_exactly_one_chunk():
    document = Document(doc_id="d", text="a" * 500, sentences=(Span(0, 500),))
    assert chunk_document(document, "document", 1, 1) == (Span(0, 500),)


def test_an_unknown_strategy_is_a_usage_error():
    document = Document(doc_id="d", text="abc", sentences=(Span(0, 3),))
    with pytest.raises(UsageError, match="unknown chunking strategy"):
        chunk_document(document, "semantic", 1, 1)


def test_a_chunking_names_itself_from_its_parameters(corpus):
    assert build_chunking(corpus.documents, "fixed", 400, 300).name == "fixed-400-300"


def test_the_document_chunking_is_named_without_parameters(corpus):
    assert build_chunking(corpus.documents, "document").name == "document"


def test_the_overlap_is_the_size_minus_the_stride(corpus):
    assert build_chunking(corpus.documents, "fixed", 400, 300).overlap == 100


def test_the_overlap_of_a_non_overlapping_chunking_is_zero(corpus):
    assert build_chunking(corpus.documents, "fixed", 400, 400).overlap == 0


def test_chunks_are_grouped_by_document(fixed_chunking, corpus):
    grouped = fixed_chunking.by_document()
    assert set(grouped) == {document.doc_id for document in corpus.documents}


def test_every_plan_entry_builds(corpus):
    for entry in PLAN:
        assert build_chunking(corpus.documents, *entry).count > 0


def test_the_guaranteed_length_is_the_overlap_plus_one():
    """The closed form, stated as a test so it is checked rather than claimed."""
    chunking = Chunking(strategy="fixed", size=400, stride=300, chunks=())
    assert guaranteed_length(chunking) == 101
    assert guaranteed_length(chunking) == chunking.overlap + 1


def test_a_non_uniform_strategy_has_no_single_guarantee():
    """None rather than zero, because the distinction is the honest part."""
    assert guaranteed_length(Chunking(strategy="sentence", size=2, stride=1, chunks=())) is None


def test_every_answer_up_to_the_guarantee_survives_at_every_position():
    """The closed form checked by exhaustion on a small case.

    For windows of size S advanced by T, an answer of length L is contained
    somewhere for every start position if and only if L is at most S minus T plus
    one. This walks every position for the boundary length and the one above it.
    """
    size, stride, length = 40, 30, 11
    document = Document(doc_id="d", text="x" * 400, sentences=(Span(0, 400),))
    spans = chunk_document(document, "fixed", size, stride)
    chunks = tuple(Chunk("d", index, span) for index, span in enumerate(spans))
    for start in range(0, 400 - length):
        answer = Span(start, start + length)
        question = Question(qid="q", text="?", doc_id="d", answer=answer, band=length)
        assert containment_for(question, chunks, answer=answer).contained, start


def test_one_character_above_the_guarantee_fails_somewhere():
    size, stride, length = 40, 30, 12
    document = Document(doc_id="d", text="x" * 400, sentences=(Span(0, 400),))
    spans = chunk_document(document, "fixed", size, stride)
    chunks = tuple(Chunk("d", index, span) for index, span in enumerate(spans))
    failures = 0
    for start in range(0, 400 - length):
        answer = Span(start, start + length)
        question = Question(qid="q", text="?", doc_id="d", answer=answer, band=length)
        if not containment_for(question, chunks, answer=answer).contained:
            failures += 1
    assert failures > 0


def test_more_overlap_can_lower_the_ceiling():
    """An exact counterexample to the intuition that overlap only helps.

    Window starts are multiples of the stride, so a smaller stride is not a
    superset of a larger one: with a stride of 800 the starts are 0 and 800, and
    with 600 they are 0, 600 and 1200. An answer that needs a window starting
    between 710 and 810 is contained by the first and destroyed by the second,
    even though the second has two hundred characters of overlap and the first
    has none. This is the mechanism behind the non monotonic column in exp04.
    """
    document = Document(doc_id="d", text="x" * 2000, sentences=(Span(0, 2000),))
    answer = Span(810, 1510)
    question = Question(qid="q", text="?", doc_id="d", answer=answer, band=700)

    def contained(stride: int) -> bool:
        spans = chunk_document(document, "fixed", 800, stride)
        chunks = tuple(Chunk("d", index, span) for index, span in enumerate(spans))
        return containment_for(question, chunks, answer=answer).contained

    assert contained(800)
    assert not contained(600)


def test_containment_reports_the_best_single_overlap():
    chunks = (Chunk("d", 0, Span(0, 100)), Chunk("d", 1, Span(100, 200)))
    answer = Span(60, 160)
    question = Question(qid="q", text="?", doc_id="d", answer=answer, band=100)
    result = containment_for(question, chunks, answer=answer)
    assert not result.contained
    assert result.covering_chunks == 2
    assert result.best_single_overlap == 60
    assert result.best_single_share == pytest.approx(0.6)


def test_a_covered_answer_is_assemblable_even_when_destroyed():
    chunks = (Chunk("d", 0, Span(0, 100)), Chunk("d", 1, Span(100, 200)))
    answer = Span(60, 160)
    question = Question(qid="q", text="?", doc_id="d", answer=answer, band=100)
    result = containment_for(question, chunks, answer=answer)
    assert result.assemblable
    assert not result.contained


def test_a_question_with_no_chunks_is_unanswerable():
    question = Question(qid="q", text="?", doc_id="d", answer=Span(0, 10), band=10)
    with pytest.raises(UnanswerableError, match="no chunks"):
        containment_for(question, (), answer=Span(0, 10))


def test_the_document_strategy_has_a_perfect_ceiling(corpus, document_chunking):
    assert ceiling_report(corpus, document_chunking).ceiling == 1.0


def test_a_small_fixed_chunking_destroys_the_long_answers(corpus):
    report = ceiling_report(corpus, build_chunking(corpus.documents, "fixed", 200, 200))
    by_band = report.ceiling_by_band()
    longest = max(by_band)
    assert by_band[longest][0] == 0


def test_the_ceiling_is_the_share_of_surviving_answers(corpus, fixed_chunking):
    report = ceiling_report(corpus, fixed_chunking)
    assert report.ceiling == pytest.approx((report.questions - report.destroyed) / report.questions)


def test_the_ceiling_report_bands_sum_to_the_question_count(corpus, fixed_chunking):
    report = ceiling_report(corpus, fixed_chunking)
    assert sum(total for _, total in report.ceiling_by_band().values()) == report.questions


def test_the_ceiling_report_publishes_its_resolution_floor(corpus, fixed_chunking):
    report = ceiling_report(corpus, fixed_chunking)
    assert report.resolution_floor == pytest.approx(1 / report.questions)


def test_the_ceiling_report_serialises_its_bands(corpus, fixed_chunking):
    payload = ceiling_report(corpus, fixed_chunking).as_dict()
    assert payload["ceiling_by_band"]
    assert payload["guaranteed_length"] == 1


def test_a_chunking_that_produces_nothing_for_a_real_document_is_refused():
    class Empty:
        doc_id = "d"
        text = "x" * 100
        length = 100
        sentences = (Span(0, 100),)

    with pytest.raises(UsageError):
        build_chunking((Empty(),), "nonsense", 1, 1)


def test_a_zero_sentence_window_is_refused():
    with pytest.raises(UsageError, match="sentence window must be at least 1"):
        sentence_spans((Span(0, 5),), 0, 1)


def test_a_zero_sentence_stride_is_refused():
    with pytest.raises(UsageError, match="sentence stride must be at least 1"):
        sentence_spans((Span(0, 5),), 1, 0)


def test_a_zero_recursive_size_is_refused():
    with pytest.raises(UsageError, match="chunk size must be at least 1"):
        recursive_spans("text", 0, 0)


def test_recursive_splitting_falls_through_to_a_finer_separator():
    """A text with no sentence terminator still has to be split by something."""
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    for span in recursive_spans(text, 20, 0):
        assert span.length <= 20


def test_recursive_splitting_of_a_text_with_no_separator_at_all_is_one_piece():
    text = "x" * 50
    assert recursive_spans(text, 20, 0) == (Span(0, 50),)


def test_a_document_of_no_text_produces_no_chunks():
    document = Document(doc_id="d", text="", sentences=())
    assert build_chunking((document,), "fixed", 100, 100).count == 0
