"""Policy loading refuses a broken policy at the boundary, not at the point of use."""

from __future__ import annotations

import pytest

from chunkaudit.config import DEFAULT_POLICY_PATH, load_policy, policy_from_mapping
from chunkaudit.errors import PolicyError


def test_the_committed_policy_loads(policy):
    assert policy.retrieval.top_k >= 1


def test_the_committed_policy_records_where_it_came_from(policy):
    assert policy.source == str(DEFAULT_POLICY_PATH)


def test_a_missing_policy_file_is_refused(tmp_path):
    with pytest.raises(PolicyError, match="not found"):
        load_policy(tmp_path / "absent.yaml")


def test_a_policy_file_that_is_not_yaml_is_refused(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("retrieval: [unclosed\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="not valid YAML"):
        load_policy(path)


def test_a_policy_file_holding_a_list_is_refused(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="mapping at the top level"):
        load_policy(path)


@pytest.mark.parametrize("section", ["retrieval", "audit", "corpus", "encoder"])
def test_every_top_level_section_is_required(minimal_policy_mapping, section):
    del minimal_policy_mapping[section]
    with pytest.raises(PolicyError, match=section):
        policy_from_mapping(minimal_policy_mapping)


def test_a_section_that_is_not_a_mapping_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["encoder"] = ["dimensions"]
    with pytest.raises(PolicyError, match="must be a mapping"):
        policy_from_mapping(minimal_policy_mapping)


def test_a_top_k_below_one_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["retrieval"]["top_k"] = 0
    with pytest.raises(PolicyError, match="top_k"):
        policy_from_mapping(minimal_policy_mapping)


def test_an_empty_k_sweep_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["retrieval"]["sweep_k"] = []
    with pytest.raises(PolicyError, match="non empty list"):
        policy_from_mapping(minimal_policy_mapping)


def test_a_k_sweep_that_is_not_a_list_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["retrieval"]["sweep_k"] = 5
    with pytest.raises(PolicyError, match="non empty list"):
        policy_from_mapping(minimal_policy_mapping)


def test_a_k_sweep_containing_zero_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["retrieval"]["sweep_k"] = [0, 5]
    with pytest.raises(PolicyError, match="at least 1"):
        policy_from_mapping(minimal_policy_mapping)


def test_a_descending_k_sweep_is_refused(minimal_policy_mapping):
    """Ascending order is assumed by every table that reads it."""
    minimal_policy_mapping["retrieval"]["sweep_k"] = [10, 3]
    with pytest.raises(PolicyError, match="ascending"):
        policy_from_mapping(minimal_policy_mapping)


def test_a_single_document_corpus_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["corpus"]["documents"] = 1
    with pytest.raises(PolicyError, match="documents"):
        policy_from_mapping(minimal_policy_mapping)


def test_zero_questions_per_document_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["corpus"]["questions_per_document"] = 0
    with pytest.raises(PolicyError, match="questions_per_document"):
        policy_from_mapping(minimal_policy_mapping)


def test_a_single_span_band_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["corpus"]["span_chars"] = [150]
    with pytest.raises(PolicyError, match="at least two band lengths"):
        policy_from_mapping(minimal_policy_mapping)


def test_a_span_band_of_a_few_characters_is_refused_with_the_reason(minimal_policy_mapping):
    minimal_policy_mapping["corpus"]["span_chars"] = [3, 150]
    with pytest.raises(PolicyError, match="containment stops meaning anything"):
        policy_from_mapping(minimal_policy_mapping)


def test_descending_span_bands_are_refused(minimal_policy_mapping):
    minimal_policy_mapping["corpus"]["span_chars"] = [400, 40]
    with pytest.raises(PolicyError, match="ascending"):
        policy_from_mapping(minimal_policy_mapping)


def test_too_few_encoder_dimensions_are_refused_with_the_reason(minimal_policy_mapping):
    minimal_policy_mapping["encoder"]["dimensions"] = 64
    with pytest.raises(PolicyError, match="collisions dominate"):
        policy_from_mapping(minimal_policy_mapping)


@pytest.mark.parametrize("value", [1, 9])
def test_an_ngram_outside_the_usable_range_is_refused(minimal_policy_mapping, value):
    minimal_policy_mapping["encoder"]["ngram"] = value
    with pytest.raises(PolicyError, match="ngram"):
        policy_from_mapping(minimal_policy_mapping)


@pytest.mark.parametrize(
    "field", ["ceiling_floor", "material_gap", "unattributable_tolerance", "assumed_prevalence"]
)
def test_a_share_outside_the_unit_interval_is_refused(minimal_policy_mapping, field):
    minimal_policy_mapping["audit"][field] = 1.5
    with pytest.raises(PolicyError, match=field):
        policy_from_mapping(minimal_policy_mapping)


def test_a_zero_share_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["audit"]["material_gap"] = 0.0
    with pytest.raises(PolicyError, match="material_gap"):
        policy_from_mapping(minimal_policy_mapping)


def test_a_non_numeric_share_is_refused(minimal_policy_mapping):
    minimal_policy_mapping["audit"]["material_gap"] = "small"
    with pytest.raises(PolicyError, match="must be a number"):
        policy_from_mapping(minimal_policy_mapping)


def test_the_question_count_is_the_product(minimal_policy_mapping):
    resolved = policy_from_mapping(minimal_policy_mapping)
    assert resolved.corpus.questions == 360


def test_the_resolution_floor_is_one_over_the_question_count(minimal_policy_mapping):
    resolved = policy_from_mapping(minimal_policy_mapping)
    assert resolved.resolution_floor == pytest.approx(1 / 360)


def test_a_policy_is_frozen(policy):
    with pytest.raises(AttributeError):
        policy.audit.ceiling_floor = 0.1
