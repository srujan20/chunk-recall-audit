"""The corpus, and why its answer spans are character offsets rather than text.

Every claim in this repository is about whether a chunk contains an answer whole.
That is a statement about offsets, so the corpus records offsets: a span is a half
open interval into the document string, and containment is an interval question
with an exact answer. Recording the answer as text instead would have made
containment a substring search, which finds the wrong copy whenever the corpus
contains a near duplicate, and this corpus contains near duplicates deliberately.

The documents are generated. That buys the exactness the whole argument rests on
and it is the cost stated in the README: these are not real documents, and the
rates measured here are properties of this corpus. What transfers is the ceiling
arithmetic, which is a property of the chunker.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import UnanswerableError

TOPICS = (
    "billing",
    "provisioning",
    "authentication",
    "retention",
    "throttling",
    "replication",
    "indexing",
    "encryption",
)

SUBJECTS = (
    "the ingest worker",
    "the archive tier",
    "the session broker",
    "the schema registry",
    "the rate limiter",
    "the replica set",
    "the query planner",
    "the key rotation job",
)

FILLER = (
    "Operators generally leave this alone during a migration window.",
    "The behaviour has been stable across the last four releases.",
    "Nothing in this section changes when the cluster is drained.",
    "This is recorded for completeness and rarely consulted.",
    "The defaults were chosen before the current sharding scheme existed.",
    "Support tickets on this topic are usually resolved by a restart.",
    "A longer discussion of the trade offs appears in the design notes.",
    "The metric is exported but no dashboard reads it today.",
)


@dataclass(frozen=True)
class Span:
    """A half open character interval, which is the unit everything here measures."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise UnanswerableError(f"a span cannot start before the document: {self.start}")
        if self.end <= self.start:
            raise UnanswerableError(
                f"a span must cover at least one character, got [{self.start}, {self.end})"
            )

    @property
    def length(self) -> int:
        return self.end - self.start

    def contains(self, other: Span) -> bool:
        """True when this span holds the whole of the other one.

        The distinction this method exists for: containment is what a single
        retrieved chunk needs in order to answer on its own, and overlap is what
        every published retrieval metric actually measures.
        """
        return self.start <= other.start and other.end <= self.end

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end

    def intersection(self, other: Span) -> int:
        return max(0, min(self.end, other.end) - max(self.start, other.start))


@dataclass(frozen=True)
class Document:
    doc_id: str
    text: str
    sentences: tuple[Span, ...]

    def __post_init__(self) -> None:
        for span in self.sentences:
            if span.end > len(self.text):
                raise UnanswerableError(
                    f"document {self.doc_id} has a sentence ending at {span.end} "
                    f"in a text of {len(self.text)} characters"
                )

    @property
    def length(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class Question:
    """One question, its document, and the exact span that answers it."""

    qid: str
    text: str
    doc_id: str
    answer: Span
    band: int

    @property
    def answer_length(self) -> int:
        return self.answer.length


@dataclass(frozen=True)
class Corpus:
    documents: tuple[Document, ...]
    questions: tuple[Question, ...]

    def __post_init__(self) -> None:
        if not self.questions:
            raise UnanswerableError("a corpus with no questions cannot be audited")
        known = {document.doc_id: document for document in self.documents}
        for question in self.questions:
            document = known.get(question.doc_id)
            if document is None:
                raise UnanswerableError(
                    f"question {question.qid} names document {question.doc_id}, which is absent"
                )
            if question.answer.end > document.length:
                raise UnanswerableError(
                    f"question {question.qid} has an answer ending at {question.answer.end} "
                    f"in a document of {document.length} characters"
                )

    @property
    def by_id(self) -> dict[str, Document]:
        return {document.doc_id: document for document in self.documents}

    def answer_text(self, question: Question) -> str:
        document = self.by_id[question.doc_id]
        return document.text[question.answer.start : question.answer.end]


def _sentence_spans(text: str) -> tuple[Span, ...]:
    """Split on the sentence terminator, keeping offsets rather than strings.

    Written by hand because the offsets are the whole point: a splitter that
    returns strings forces a substring search to recover positions, and this
    corpus contains near duplicate sentences on purpose.
    """
    spans: list[Span] = []
    start = 0
    for index, character in enumerate(text):
        if character == "." and (index + 1 == len(text) or text[index + 1] == " "):
            spans.append(Span(start, index + 1))
            start = index + 2
    if start < len(text):
        spans.append(Span(start, len(text)))
    return tuple(spans)


CLAUSES = (
    "after the current window closes",
    "once every replica has acknowledged the write",
    "unless an operator has pinned the previous generation",
    "and the outcome is recorded in the audit trail",
    "which the reconciliation job reads on its next pass",
    "before any downstream consumer is notified",
    "with the deferred entries retried on a fixed schedule",
)

CONTINUATIONS = (
    "The rule is applied before any retry counter is incremented",
    "Nothing else in the pipeline is permitted to observe the interim state",
    "The same ordering holds when the operation is replayed from the log",
)


def _answer_text(rng: np.random.Generator, topic: str, subject: str, target: int) -> str:
    """Build an answer of roughly the target character length.

    Long answers are built from several sentences rather than one very long one,
    and that detail decides whether the corpus can say anything about sentence
    based chunking at all. The first version of this generator made every answer
    a single sentence, which handed every sentence window strategy a containment
    ceiling of exactly one by construction. The comparison it produced was not a
    finding, it was a restatement of how the corpus had been built.

    Answers longer than roughly two hundred characters now span two or three
    sentences, which is also what a real answer to a procedural question looks
    like: a rule, then its qualification.
    """
    head = f"For {topic}, {subject} applies the documented rule"
    parts = [head]
    while len(" ".join(parts)) < min(target, 190) - 12:
        parts.append(CLAUSES[int(rng.integers(0, len(CLAUSES)))])
    sentences = [" ".join(parts).rstrip(",") + "."]
    while len(" ".join(sentences)) < target - 40:
        sentences.append(CONTINUATIONS[int(rng.integers(0, len(CONTINUATIONS)))] + ".")
    return " ".join(sentences)


def _distractor(topic: str, subject: str) -> str:
    """A sentence carrying the question's key terms and none of its answer.

    Without these a lexical retriever scores far too well and the corpus stops
    being able to tell a retrieval failure from a chunking one.
    """
    return f"For {topic}, {subject} is also mentioned in the deprecation notice."


def build_corpus(
    *,
    documents: int,
    questions_per_document: int,
    span_chars: tuple[int, ...],
    seed: int = 20260824,
) -> Corpus:
    """Generate the corpus. Deterministic in the seed, and offline by construction."""
    if documents < 2:
        raise UnanswerableError(f"a corpus needs at least two documents, got {documents}")
    if questions_per_document < 1:
        raise UnanswerableError(
            f"a corpus needs at least one question per document, got {questions_per_document}"
        )
    rng = np.random.default_rng(seed)
    built_documents: list[Document] = []
    built_questions: list[Question] = []

    for index in range(documents):
        doc_id = f"doc-{index:04d}"
        topic = TOPICS[index % len(TOPICS)]
        # A token unique to this document, carried by the question, the answer and
        # the distractor. Without it the corpus was unanswerable rather than hard:
        # eight topics and eight subjects repeat every sixty four documents, so a
        # question naming only those two matched fifteen documents equally well and
        # every retriever scored near chance. The failure attribution then reported
        # a retrieval problem that was really a labelling problem.
        cluster = f"kx-{index:04d}"
        pieces: list[str] = []
        answers: list[tuple[Span, str, int]] = []
        for slot in range(questions_per_document):
            subject = f"{SUBJECTS[(index + slot) % len(SUBJECTS)]} on cluster {cluster}"
            band = int(span_chars[slot % len(span_chars)])
            for _ in range(int(rng.integers(1, 4))):
                pieces.append(FILLER[int(rng.integers(0, len(FILLER)))])
            pieces.append(_distractor(topic, subject))
            answer = _answer_text(rng, topic, subject, band)
            offset = len(" ".join(pieces)) + 1 if pieces else 0
            pieces.append(answer)
            answers.append((Span(offset, offset + len(answer)), subject, band))
            for _ in range(int(rng.integers(1, 3))):
                pieces.append(FILLER[int(rng.integers(0, len(FILLER)))])
        text = " ".join(pieces)
        document = Document(doc_id=doc_id, text=text, sentences=_sentence_spans(text))
        built_documents.append(document)
        for slot, (span, subject, band) in enumerate(answers):
            if text[span.start : span.end] == "" or span.end > len(text):
                # An assertion about this function's own offset arithmetic rather
                # than a condition any caller can produce, so it is not measured.
                # It is kept because a mislaid span is otherwise silent: every
                # downstream number would be computed against the wrong characters
                # and still look plausible.
                raise UnanswerableError(  # pragma: no cover
                    f"the generator placed an answer for {doc_id} outside its own document"
                )
            built_questions.append(
                Question(
                    qid=f"{doc_id}-q{slot}",
                    text=f"What rule does {subject} apply for {topic}?",
                    doc_id=doc_id,
                    answer=span,
                    band=band,
                )
            )
    return Corpus(documents=tuple(built_documents), questions=tuple(built_questions))
