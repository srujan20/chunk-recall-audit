"""Shared fixtures.

Every fixture is smaller than the shipped corpus. The properties under test are
properties of the code rather than of the corpus size, and a suite that takes
four minutes gets run less often than one that takes thirty seconds.
"""

from __future__ import annotations

import numpy as np
import pytest

from chunkaudit.chunking import Chunking, build_chunking
from chunkaudit.config import Policy, load_policy, policy_from_mapping
from chunkaudit.documents import Corpus, build_corpus


@pytest.fixture(scope="session")
def policy() -> Policy:
    return load_policy()


@pytest.fixture(scope="session")
def small_policy() -> Policy:
    return policy_from_mapping(
        {
            "retrieval": {"top_k": 5, "sweep_k": [1, 5]},
            "audit": {
                "ceiling_floor": 0.95,
                "material_gap": 0.02,
                "unattributable_tolerance": 0.01,
                "assumed_prevalence": 0.25,
            },
            "corpus": {"documents": 12, "questions_per_document": 3, "span_chars": [40, 150, 400]},
            "encoder": {"dimensions": 1024, "ngram": 4},
        },
        source="<small fixture>",
    )


@pytest.fixture(scope="session")
def corpus(small_policy: Policy) -> Corpus:
    return build_corpus(
        documents=small_policy.corpus.documents,
        questions_per_document=small_policy.corpus.questions_per_document,
        span_chars=small_policy.corpus.span_chars,
    )


@pytest.fixture(scope="session")
def fixed_chunking(corpus: Corpus) -> Chunking:
    return build_chunking(corpus.documents, "fixed", 400, 400)


@pytest.fixture(scope="session")
def sentence_chunking(corpus: Corpus) -> Chunking:
    return build_chunking(corpus.documents, "sentence", 1, 1)


@pytest.fixture(scope="session")
def document_chunking(corpus: Corpus) -> Chunking:
    return build_chunking(corpus.documents, "document")


@pytest.fixture
def minimal_policy_mapping() -> dict[str, object]:
    return {
        "retrieval": {"top_k": 5, "sweep_k": [1, 3, 5]},
        "audit": {
            "ceiling_floor": 0.95,
            "material_gap": 0.02,
            "unattributable_tolerance": 0.01,
            "assumed_prevalence": 0.25,
        },
        "corpus": {"documents": 120, "questions_per_document": 3, "span_chars": [40, 150, 400]},
        "encoder": {"dimensions": 4096, "ngram": 4},
    }


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(12345)
