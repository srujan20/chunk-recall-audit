"""The verdicts, the sweep, and the report that gets photographed."""

from __future__ import annotations

import re

import pytest

from chunkaudit.audit import EXIT_CODES, Verdict, audit, decide_verdict
from chunkaudit.ceiling import ceiling_report
from chunkaudit.chunking import build_chunking
from chunkaudit.metrics import evaluate
from chunkaudit.pipeline import chunkings_for, corpus_for, row_from, run_audit, sweep
from chunkaudit.report import (
    STYLED_CLASSES,
    STYLESHEET,
    VERDICT_CLASS,
    VERDICT_TEXT,
    render_html,
    render_sweep_html,
    render_text,
)
from chunkaudit.retrieval import rank


@pytest.fixture(scope="module")
def audited(corpus_module, small_policy_module):
    chunking = build_chunking(corpus_module.documents, "fixed", 200, 200)
    report = ceiling_report(corpus_module, chunking)
    rankings = rank("bm25", corpus_module, chunking, small_policy_module)
    metrics = evaluate(corpus_module, chunking, rankings, retriever="bm25", k=5)
    return audit(report, metrics, small_policy_module)


@pytest.fixture(scope="module")
def small_policy_module():
    from chunkaudit.config import policy_from_mapping

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
        source="<module fixture>",
    )


@pytest.fixture(scope="module")
def corpus_module(small_policy_module):
    return corpus_for(small_policy_module)


@pytest.fixture(scope="module")
def swept(small_policy_module, corpus_module):
    return sweep(
        small_policy_module,
        plan=(("fixed", 200, 200), ("fixed", 800, 800), ("document", 1, 1)),
        retrievers=("bm25", "oracle"),
        ks=(1, 5),
        corpus=corpus_module,
    )


def test_every_verdict_has_an_exit_code():
    for verdict in Verdict:
        assert verdict in EXIT_CODES


def test_the_three_exit_codes_are_distinct():
    assert sorted(EXIT_CODES.values()) == [0, 1, 2]


def test_a_high_ceiling_and_a_small_gap_survives(small_policy_module):
    assert decide_verdict(0.99, 0.001, 0.0, small_policy_module) is Verdict.SURVIVES


def test_a_low_ceiling_is_destroying(small_policy_module):
    assert decide_verdict(0.50, 0.001, 0.0, small_policy_module) is Verdict.DESTROYING


def test_a_large_gap_is_destroying_even_with_a_high_ceiling(small_policy_module):
    assert decide_verdict(0.99, 0.10, 0.0, small_policy_module) is Verdict.DESTROYING


def test_unattributable_questions_are_checked_first(small_policy_module):
    """A corpus whose causes cannot be told apart cannot support a claim about them."""
    assert decide_verdict(0.10, 0.90, 0.5, small_policy_module) is Verdict.UNATTRIBUTABLE


def test_the_audit_reports_a_destroying_verdict_for_a_small_chunker(audited):
    assert audited.verdict is Verdict.DESTROYING
    assert audited.exit_code == 1


def test_the_audit_reports_no_unattributable_questions(audited):
    assert audited.unattributable.numerator == 0
    assert audited.unattributable.is_measured_zero


def test_the_headroom_is_the_distance_to_the_ceiling(audited):
    assert audited.headroom == pytest.approx(
        audited.ceiling.ceiling - audited.metrics.span_complete_recall.value
    )


def test_the_attainable_share_is_the_headroom_over_the_shortfall(audited):
    shortfall = 1.0 - audited.metrics.span_complete_recall.value
    assert audited.attainable_share == pytest.approx(audited.headroom / shortfall)


def test_a_perfect_audit_has_no_attainable_share(corpus_module, small_policy_module):
    chunking = build_chunking(corpus_module.documents, "document")
    result = run_audit(corpus_module, chunking, small_policy_module, retriever="oracle", k=5)
    assert result.metrics.span_complete_recall.value == 1.0
    assert result.attainable_share == 0.0


def test_an_audit_serialises_its_ceiling_and_its_metrics(audited):
    payload = audited.as_dict()
    assert payload["ceiling"]["ceiling"] == audited.ceiling.ceiling
    assert payload["metrics"]["gap"] == audited.metrics.gap


def test_the_sweep_covers_every_combination(swept):
    assert len(swept) == 3 * 2 * 2


def test_the_sweep_is_deterministic(small_policy_module, corpus_module):
    plan = (("fixed", 400, 400),)
    left = sweep(
        small_policy_module, plan=plan, retrievers=("bm25",), ks=(5,), corpus=corpus_module
    )
    right = sweep(
        small_policy_module, plan=plan, retrievers=("bm25",), ks=(5,), corpus=corpus_module
    )
    assert [row.as_dict() for row in left] == [row.as_dict() for row in right]


def test_every_row_carries_the_chunking_parameters(swept):
    """A ceiling without its size and stride is not a number anybody can act on."""
    for row in swept:
        assert row.strategy
        assert row.chunk_count > 0


def test_the_document_rows_have_a_perfect_ceiling(swept):
    for row in swept:
        if row.chunking == "document":
            assert row.ceiling == 1.0


def test_no_row_reports_a_recall_above_its_ceiling(swept):
    for row in swept:
        assert row.span_complete_recall <= row.ceiling + 1e-12


def test_the_row_causes_sum_to_the_answered_questions(swept):
    for row in swept:
        answered = round(row.span_complete_recall * row.questions)
        assert (
            answered + row.destroyed_by_chunking + row.missed_by_retrieval + (row.unattributable)
            == row.questions
        )


def test_chunkings_for_builds_one_per_plan_entry(corpus_module):
    plan = (("fixed", 200, 200), ("document", 1, 1))
    assert len(chunkings_for(corpus_module, plan)) == 2


def test_a_row_records_the_verdict_it_came_from(audited):
    assert row_from(audited).verdict == audited.verdict.value


def test_every_class_used_in_the_markup_has_a_stylesheet_rule():
    """Pins the failure a green-on-green verdict badge caused on two earlier projects."""
    for name in STYLED_CLASSES:
        assert re.search(rf"\.{re.escape(name)}\s*[,{{\s]", STYLESHEET), name


def test_every_verdict_has_display_text_and_a_declared_class():
    for verdict in Verdict:
        assert verdict in VERDICT_TEXT
        assert VERDICT_CLASS[verdict] in STYLED_CLASSES


def test_the_text_report_prints_the_ceiling_before_any_retrieval_number(audited):
    text = render_text(audited)
    assert text.index("containment ceiling") < text.index("chunk level recall")


def test_the_text_report_names_the_guarantee(audited):
    assert "guaranteed to survive at any position" in render_text(audited)


def test_the_text_report_says_when_the_guarantee_is_not_a_number(
    corpus_module, small_policy_module
):
    chunking = build_chunking(corpus_module.documents, "sentence", 2, 1)
    result = run_audit(corpus_module, chunking, small_policy_module, retriever="bm25", k=5)
    assert "not a single number" in render_text(result)


def test_the_text_report_reports_how_many_failures_a_retriever_could_fix(audited):
    assert "could be fixed by a better retriever" in render_text(audited)


def test_the_text_report_ends_with_a_newline(audited):
    assert render_text(audited).endswith("\n")


def test_the_html_report_is_a_complete_document(audited):
    html = render_html(audited)
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")


def test_the_html_report_inlines_its_stylesheet(audited):
    assert "<style>" in render_html(audited)


def test_the_html_report_marks_the_ceiling_on_every_bar(audited):
    assert render_html(audited).count('<div class="bar-ceiling"') == 3


def test_the_html_report_escapes_a_hostile_chunking_name(audited):
    from dataclasses import replace

    injected = replace(
        audited, ceiling=replace(audited.ceiling, chunking="<script>alert(1)</script>")
    )
    html = render_html(injected)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_sweep_report_is_a_complete_document(swept):
    html = render_sweep_html(swept, retriever="bm25", k=5)
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")


def test_the_sweep_report_sorts_the_worst_ceiling_first(swept):
    html = render_sweep_html(swept, retriever="bm25", k=5)
    assert html.index("fixed-200-200") < html.index("document")


def test_the_sweep_report_refuses_a_selection_with_no_rows(swept):
    with pytest.raises(ValueError, match="no rows for retriever"):
        render_sweep_html(swept, retriever="hashed", k=5)


def test_the_sweep_report_states_that_the_ceiling_bounds_every_retriever(swept):
    html = render_sweep_html(swept, retriever="bm25", k=5)
    assert "no retriever change can address" in html
