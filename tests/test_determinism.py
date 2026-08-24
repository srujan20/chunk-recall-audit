"""Every published figure must agree on a second run of the same command.

A repository that claims its numbers are re-measured by CI needs the second
measurement to match the first. Thread count, hash seed and wall clock are the
three usual culprits and none of them may appear in a result. The hash seed is
the live risk here: a retriever built on Python's salted hash would move between
runs on the same machine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pytest

from chunkaudit.chunking import build_chunking
from chunkaudit.metrics import evaluate
from chunkaudit.pipeline import corpus_for, sweep
from chunkaudit.retrieval import RUNNABLE, rank

PLAN = (("fixed", 400, 400), ("document", 1, 1))


def test_two_sweeps_agree_row_for_row(small_policy):
    left = sweep(small_policy, plan=PLAN, retrievers=("bm25", "hashed"), ks=(5,))
    right = sweep(small_policy, plan=PLAN, retrievers=("bm25", "hashed"), ks=(5,))
    assert [row.as_dict() for row in left] == [row.as_dict() for row in right]


@pytest.mark.parametrize("name", RUNNABLE)
def test_a_ranking_does_not_move_with_the_thread_count(
    name, corpus, fixed_chunking, small_policy, monkeypatch
):
    baseline = rank(name, corpus, fixed_chunking, small_policy)
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    repeated = rank(name, corpus, fixed_chunking, small_policy)
    for one, two in zip(baseline, repeated, strict=True):
        assert np.array_equal(one.order, two.order)


def test_a_result_does_not_move_with_the_hash_seed(tmp_path):
    """Two audits in fresh interpreters with different hash seeds must agree.

    This is the check the hashed retriever exists to pass. Python's built in hash
    is salted per process, so a vectoriser built on it would give a different
    ranking on every run and every published retrieval figure would be a
    statement about one process.
    """
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "retrieval:\n  top_k: 5\n  sweep_k: [5]\n"
        "audit:\n  ceiling_floor: 0.95\n  material_gap: 0.02\n"
        "  unattributable_tolerance: 0.01\n  assumed_prevalence: 0.25\n"
        "corpus:\n  documents: 8\n  questions_per_document: 2\n  span_chars: [40, 400]\n"
        "encoder:\n  dimensions: 1024\n  ngram: 4\n",
        encoding="utf-8",
    )
    outputs = []
    for seed in ("0", "9182736"):
        environment = dict(os.environ, PYTHONHASHSEED=seed)
        target = tmp_path / f"out-{seed}.json"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "chunkaudit",
                "audit",
                "--retriever",
                "hashed",
                "--policy",
                str(policy),
                "--json",
                str(target),
            ],
            env=environment,
            capture_output=True,
            check=False,
        )
        outputs.append(json.loads(target.read_text(encoding="utf-8")))
    assert outputs[0] == outputs[1]


def test_the_corpus_is_identical_across_two_builds(small_policy):
    left = corpus_for(small_policy)
    right = corpus_for(small_policy)
    assert [document.text for document in left.documents] == [
        document.text for document in right.documents
    ]


def test_a_metric_set_is_identical_across_two_evaluations(corpus, small_policy):
    chunking = build_chunking(corpus.documents, "fixed", 400, 300)
    rankings = rank("hashed", corpus, chunking, small_policy)
    left = evaluate(corpus, chunking, rankings, retriever="hashed", k=5)
    right = evaluate(corpus, chunking, rankings, retriever="hashed", k=5)
    assert left.as_dict() == right.as_dict()
