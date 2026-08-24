"""The retrievers, and why none of them can beat the ceiling.

Four retrievers that run, and one that is written and, in the environment this
repository was built in, cannot be.

    bm25      Okapi BM25 over chunk token bags, implemented here
    hashed    cosine over hashed character n gram vectors with inverse document
              frequency weighting, also implemented here
    oracle    ranks by overlap with the answer, which is an upper bound on any
              retriever that could exist
    random    seeded, as the floor a comparison needs to be read against

The hashed retriever is a lexical vectoriser and this module will not call it
anything else. It hashes character n grams into a fixed number of dimensions and
weights them by inverse document frequency. That is a real retrieval method with
real behaviour on misspellings and morphology, and it is not a neural encoder.
Nothing in this repository claims a transformer produced any published number.

The optional `sentence_transformers` path exists because the question people ask
is about a dense encoder. It is fenced behind an extra, and ADR-003 states plainly
that the model weights host was unreachable from this environment, so it has never
been run against a real model. What that ADR also states is why it does not
threaten the headline: the containment ceiling bounds every retriever, so a
retriever this repository could not test is bounded by it too.

Retrieval runs over the whole corpus rather than within the answer's own
document. Restricting it to the right document would remove the only thing that
makes a retrieval failure possible and would turn the failure attribution into a
tautology.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .chunking import Chunking
from .config import Policy
from .documents import Corpus
from .errors import MissingDependencyError, UnanswerableError, UsageError

TOKEN = re.compile(r"[a-z0-9]+")
BM25_K1 = 1.5
BM25_B = 0.75
RANDOM_SEED = 90210


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


@dataclass(frozen=True)
class Ranking:
    """One question's ranked chunk indices, best first."""

    qid: str
    order: np.ndarray

    def top(self, k: int) -> np.ndarray:
        if k < 1:
            raise UsageError(f"k must be at least 1, got {k}")
        return self.order[:k]


def _chunk_texts(corpus: Corpus, chunking: Chunking) -> list[str]:
    documents = corpus.by_id
    return [
        documents[chunk.doc_id].text[chunk.span.start : chunk.span.end] for chunk in chunking.chunks
    ]


def _hash_matrix(texts: list[str], *, dimensions: int, ngram: int) -> np.ndarray:
    """Hashed character n gram counts, one row per text.

    Python's built in hash is deliberately not used. It is salted per process
    unless PYTHONHASHSEED is set, so a published retrieval figure would move
    between runs on the same machine, which is exactly the kind of number this
    repository exists to complain about. The mixing below is a fixed integer
    hash with no process state in it at all.
    """
    matrix = np.zeros((len(texts), dimensions), dtype=np.float32)
    for row, text in enumerate(texts):
        lowered = text.lower()
        for start in range(max(1, len(lowered) - ngram + 1)):
            gram = lowered[start : start + ngram]
            digest = 0
            for character in gram:
                digest = (digest * 131 + ord(character)) & 0xFFFFFFFF
            matrix[row, digest % dimensions] += 1.0
    return matrix


def _idf_weight(matrix: np.ndarray) -> np.ndarray:
    documents = matrix.shape[0]
    present = (matrix > 0).sum(axis=0)
    return np.log((1.0 + documents) / (1.0 + present)).astype(np.float32)


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return matrix / norms


def hashed_rankings(corpus: Corpus, chunking: Chunking, policy: Policy) -> list[Ranking]:
    """Cosine similarity over inverse document frequency weighted hashed n grams."""
    texts = _chunk_texts(corpus, chunking)
    if not texts:
        raise UnanswerableError("a chunking with no chunks cannot be retrieved from")
    dimensions = policy.encoder.dimensions
    ngram = policy.encoder.ngram
    chunk_matrix = _hash_matrix(texts, dimensions=dimensions, ngram=ngram)
    weights = _idf_weight(chunk_matrix)
    chunk_matrix = _normalise(chunk_matrix * weights)
    query_matrix = _normalise(
        _hash_matrix(
            [question.text for question in corpus.questions],
            dimensions=dimensions,
            ngram=ngram,
        )
        * weights
    )
    scores = query_matrix @ chunk_matrix.T
    return _rank(corpus, scores)


def bm25_rankings(corpus: Corpus, chunking: Chunking, policy: Policy) -> list[Ranking]:
    """Okapi BM25, written out because the parameters are part of the finding."""
    del policy
    texts = _chunk_texts(corpus, chunking)
    tokenised = [tokenize(text) for text in texts]
    vocabulary: dict[str, int] = {}
    for tokens in tokenised:
        for token in tokens:
            vocabulary.setdefault(token, len(vocabulary))
    if not vocabulary:
        raise UnanswerableError("the chunk texts contain no tokens, so BM25 has nothing to score")

    counts = np.zeros((len(tokenised), len(vocabulary)), dtype=np.float32)
    for row, tokens in enumerate(tokenised):
        for token in tokens:
            counts[row, vocabulary[token]] += 1.0
    lengths = counts.sum(axis=1)
    average = float(lengths.mean()) or 1.0
    document_frequency = (counts > 0).sum(axis=0)
    idf = np.log(
        1.0 + (len(tokenised) - document_frequency + 0.5) / (document_frequency + 0.5)
    ).astype(np.float32)
    denominator = counts + (BM25_K1 * (1.0 - BM25_B + BM25_B * lengths / average))[:, None]
    weighted = ((counts * (BM25_K1 + 1.0)) / denominator) * idf

    query_matrix = np.zeros((len(corpus.questions), len(vocabulary)), dtype=np.float32)
    for row, question in enumerate(corpus.questions):
        for token in tokenize(question.text):
            index = vocabulary.get(token)
            if index is not None:
                query_matrix[row, index] = 1.0
    scores = query_matrix @ weighted.T
    return _rank(corpus, scores)


def oracle_rankings(corpus: Corpus, chunking: Chunking, policy: Policy) -> list[Ranking]:
    """Ranks by how much of the answer each chunk holds. An upper bound, not a method.

    Included because a comparison of retrievers with no upper bound in it cannot
    say whether the remaining error is the retriever's fault. This one sees the
    answer, which no retriever does, and it still cannot exceed the ceiling.
    """
    del policy
    scores = np.zeros((len(corpus.questions), chunking.count), dtype=np.float32)
    index_of = {chunk.key: position for position, chunk in enumerate(chunking.chunks)}
    grouped = chunking.by_document()
    for row, question in enumerate(corpus.questions):
        for chunk in grouped.get(question.doc_id, ()):
            overlap = chunk.span.intersection(question.answer)
            if not overlap:
                continue
            complete = 1.0 if chunk.span.contains(question.answer) else 0.0
            scores[row, index_of[chunk.key]] = complete * 1000.0 + overlap
    return _rank(corpus, scores)


def random_rankings(corpus: Corpus, chunking: Chunking, policy: Policy) -> list[Ranking]:
    """A seeded shuffle, which is the floor every other number is read against."""
    del policy
    rng = np.random.default_rng(RANDOM_SEED)
    return [
        Ranking(qid=question.qid, order=rng.permutation(chunking.count))
        for question in corpus.questions
    ]


def sentence_transformer_rankings(
    corpus: Corpus, chunking: Chunking, policy: Policy, *, model: str = "all-MiniLM-L6-v2"
) -> list[Ranking]:
    """Dense retrieval with a sentence transformer. Written, never run here.

    The model weights host is not reachable from the environment this repository
    was built in, so this path has never produced a number and no published
    figure comes from it. ADR-003 states which claim would change if it had, and
    why the headline claim is not one of them: the containment ceiling bounds
    every retriever, including this one.

    The import is inside the function and below the argument validation, so a
    caller who asks for a model with an empty name hears about the name rather
    than about a missing package.
    """
    if not model or not model.strip():
        raise UsageError("a sentence transformer model name cannot be empty")
    del policy
    try:
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "the sentence transformer retriever needs the optional extra. Install it with "
            "pip install -e '.[transformers]' and note that it also needs network access to "
            "the model weights host, which ADR-003 explains was unavailable here."
        ) from exc
    encoder = SentenceTransformer(model)  # pragma: no cover
    chunk_matrix = _normalise(  # pragma: no cover
        np.asarray(encoder.encode(_chunk_texts(corpus, chunking)), dtype=np.float32)
    )
    query_matrix = _normalise(  # pragma: no cover
        np.asarray(
            encoder.encode([question.text for question in corpus.questions]), dtype=np.float32
        )
    )
    return _rank(corpus, query_matrix @ chunk_matrix.T)  # pragma: no cover


def _rank(corpus: Corpus, scores: np.ndarray) -> list[Ranking]:
    """Turn a score matrix into rankings, breaking ties by chunk index.

    The tie break is not cosmetic. BM25 gives many chunks a score of exactly zero
    when a question shares no token with them, and argsort's ordering among equal
    values is not something to publish a retrieval figure on top of. Sorting by
    the negated score and then by index makes the ordering total and reproducible.
    """
    if scores.shape[0] != len(corpus.questions):
        raise UnanswerableError(
            f"the score matrix has {scores.shape[0]} rows for {len(corpus.questions)} questions"
        )
    indices = np.arange(scores.shape[1])
    return [
        Ranking(
            qid=question.qid,
            order=np.lexsort((indices, -scores[row])),
        )
        for row, question in enumerate(corpus.questions)
    ]


RETRIEVERS: dict[str, Callable[[Corpus, Chunking, Policy], list[Ranking]]] = {
    "bm25": bm25_rankings,
    "hashed": hashed_rankings,
    "oracle": oracle_rankings,
    "random": random_rankings,
}

RUNNABLE = tuple(RETRIEVERS)
WRITTEN_NOT_RUN = ("sentence_transformer",)


def rank(name: str, corpus: Corpus, chunking: Chunking, policy: Policy) -> list[Ranking]:
    if name in WRITTEN_NOT_RUN:
        return sentence_transformer_rankings(corpus, chunking, policy)
    try:
        function = RETRIEVERS[name]
    except KeyError as exc:
        raise UsageError(
            f"unknown retriever {name!r}, expected one of {sorted(RETRIEVERS)} "
            f"or one of {list(WRITTEN_NOT_RUN)}"
        ) from exc
    return function(corpus, chunking, policy)
