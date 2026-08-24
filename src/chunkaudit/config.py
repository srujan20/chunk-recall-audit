"""Loading and validating the audit policy.

Strict at load time. A top_k of zero, a ceiling floor above one, or a span band
of a single character are all typos, and finding one partway through a corpus of
three hundred and sixty questions costs more than refusing it at the boundary.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import PolicyError

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "configs" / "policy.yaml"


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if not isinstance(mapping, dict):
        raise PolicyError(
            f"policy section {where!r} must be a mapping, got {type(mapping).__name__}"
        )
    if key not in mapping:
        raise PolicyError(f"policy section {where!r} is missing the key {key!r}")
    return mapping[key]


def _share(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{name} must be a number, got {value!r}") from exc
    if not 0.0 < number <= 1.0:
        raise PolicyError(f"{name} must lie in (0, 1], got {number}")
    return number


@dataclass(frozen=True)
class RetrievalPolicy:
    top_k: int
    sweep_k: tuple[int, ...]


@dataclass(frozen=True)
class AuditPolicy:
    ceiling_floor: float
    material_gap: float
    unattributable_tolerance: float
    assumed_prevalence: float


@dataclass(frozen=True)
class CorpusPolicy:
    documents: int
    questions_per_document: int
    span_chars: tuple[int, ...]

    @property
    def questions(self) -> int:
        return self.documents * self.questions_per_document


@dataclass(frozen=True)
class EncoderPolicy:
    dimensions: int
    ngram: int


@dataclass(frozen=True)
class Policy:
    retrieval: RetrievalPolicy
    audit: AuditPolicy
    corpus: CorpusPolicy
    encoder: EncoderPolicy
    source: str = field(default="<defaults>")

    @property
    def resolution_floor(self) -> float:
        """The smallest non zero rate this corpus size can express.

        Published next to every measured zero, because a zero over three hundred
        and sixty questions is a different statement from a zero over a million.
        """
        return 1.0 / self.corpus.questions


def load_policy(path: str | os.PathLike[str] | None = None) -> Policy:
    resolved = Path(path) if path is not None else DEFAULT_POLICY_PATH
    if not resolved.is_file():
        raise PolicyError(f"policy file not found: {resolved}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PolicyError(f"policy file {resolved} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyError(f"policy file {resolved} must contain a mapping at the top level")
    return policy_from_mapping(raw, source=str(resolved))


def policy_from_mapping(raw: dict[str, Any], *, source: str = "<mapping>") -> Policy:
    retrieval_raw = _require(raw, "retrieval", "<root>")
    audit_raw = _require(raw, "audit", "<root>")
    corpus_raw = _require(raw, "corpus", "<root>")
    encoder_raw = _require(raw, "encoder", "<root>")

    top_k = int(_require(retrieval_raw, "top_k", "retrieval"))
    if top_k < 1:
        raise PolicyError(f"retrieval.top_k must be at least 1, got {top_k}")

    sweep_raw = _require(retrieval_raw, "sweep_k", "retrieval")
    if not isinstance(sweep_raw, list) or not sweep_raw:
        raise PolicyError("retrieval.sweep_k must be a non empty list of k values")
    sweep_k = tuple(int(value) for value in sweep_raw)
    if any(value < 1 for value in sweep_k):
        raise PolicyError(f"every value in retrieval.sweep_k must be at least 1, got {sweep_k}")
    if sorted(sweep_k) != list(sweep_k):
        raise PolicyError(f"retrieval.sweep_k must be ascending, got {sweep_k}")

    documents = int(_require(corpus_raw, "documents", "corpus"))
    if documents < 2:
        raise PolicyError(f"corpus.documents must be at least 2, got {documents}")
    per_document = int(_require(corpus_raw, "questions_per_document", "corpus"))
    if per_document < 1:
        raise PolicyError(f"corpus.questions_per_document must be at least 1, got {per_document}")

    span_raw = _require(corpus_raw, "span_chars", "corpus")
    if not isinstance(span_raw, list) or len(span_raw) < 2:
        raise PolicyError("corpus.span_chars must be a list of at least two band lengths")
    span_chars = tuple(int(value) for value in span_raw)
    if any(value < 8 for value in span_chars):
        raise PolicyError(
            f"every value in corpus.span_chars must be at least 8 characters, got {span_chars}. "
            "A shorter answer is a token, and containment stops meaning anything"
        )
    if sorted(span_chars) != list(span_chars):
        raise PolicyError(f"corpus.span_chars must be ascending, got {span_chars}")

    dimensions = int(_require(encoder_raw, "dimensions", "encoder"))
    if dimensions < 256:
        raise PolicyError(
            f"encoder.dimensions must be at least 256, got {dimensions}. Below that hash "
            "collisions dominate the similarity and the retriever is measuring the hash"
        )
    ngram = int(_require(encoder_raw, "ngram", "encoder"))
    if not 2 <= ngram <= 8:
        raise PolicyError(f"encoder.ngram must lie between 2 and 8, got {ngram}")

    return Policy(
        retrieval=RetrievalPolicy(top_k=top_k, sweep_k=sweep_k),
        audit=AuditPolicy(
            ceiling_floor=_share(
                _require(audit_raw, "ceiling_floor", "audit"), "audit.ceiling_floor"
            ),
            material_gap=_share(_require(audit_raw, "material_gap", "audit"), "audit.material_gap"),
            unattributable_tolerance=_share(
                _require(audit_raw, "unattributable_tolerance", "audit"),
                "audit.unattributable_tolerance",
            ),
            assumed_prevalence=_share(
                _require(audit_raw, "assumed_prevalence", "audit"), "audit.assumed_prevalence"
            ),
        ),
        corpus=CorpusPolicy(
            documents=documents, questions_per_document=per_document, span_chars=span_chars
        ),
        encoder=EncoderPolicy(dimensions=dimensions, ngram=ngram),
        source=source,
    )
