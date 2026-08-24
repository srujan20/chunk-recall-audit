"""The CLI, and the exit codes the README promises."""

from __future__ import annotations

import json

import pytest

from chunkaudit.cli import build_parser, main

SMALL = ["--policy", "tests/data/small-policy.yaml"]


@pytest.fixture(scope="module", autouse=True)
def small_policy_file():
    """A small corpus, so the CLI suite does not pay for the shipped one each time."""
    from pathlib import Path

    path = Path("tests/data/small-policy.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "retrieval:\n  top_k: 5\n  sweep_k: [1, 5]\n"
        "audit:\n  ceiling_floor: 0.95\n  material_gap: 0.02\n"
        "  unattributable_tolerance: 0.01\n  assumed_prevalence: 0.25\n"
        "corpus:\n  documents: 10\n  questions_per_document: 3\n  span_chars: [40, 150, 400]\n"
        "encoder:\n  dimensions: 1024\n  ngram: 4\n",
        encoding="utf-8",
    )
    return path


def test_no_command_is_a_parser_error():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_the_version_flag_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "chunkaudit" in capsys.readouterr().out


def test_the_plan_lists_every_chunking(capsys):
    assert main(["plan", *SMALL]) == 0
    output = capsys.readouterr().out
    assert "fixed-200-200" in output
    assert "document" in output


def test_the_plan_names_the_retriever_that_was_never_run(capsys):
    """The honest disclosure belongs in the tool, not only in an ADR."""
    main(["plan", *SMALL])
    output = capsys.readouterr().out
    assert "written and never run" in output
    assert "ADR-003" in output


def test_the_plan_as_json_parses(capsys):
    assert main(["plan", "--json", *SMALL]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(row["chunking"] == "document" for row in payload)


def test_a_small_chunker_exits_one(capsys):
    """The headline demo, and the exit code that carries it."""
    code = main(["audit", "--size", "200", "--stride", "200", *SMALL])
    output = capsys.readouterr().out
    assert code == 1
    assert "containment ceiling" in output
    assert "could be fixed by a better retriever" in output


def test_whole_document_chunks_exit_zero(capsys):
    code = main(["audit", "--strategy", "document", *SMALL])
    capsys.readouterr()
    assert code == 0


def test_a_stride_larger_than_its_size_exits_four(capsys):
    code = main(["audit", "--size", "200", "--stride", "400", *SMALL])
    assert code == 4
    assert "usage error" in capsys.readouterr().err


def test_an_unknown_strategy_is_a_parser_error():
    with pytest.raises(SystemExit):
        main(["audit", "--strategy", "semantic"])


def test_an_unknown_retriever_is_a_parser_error():
    with pytest.raises(SystemExit):
        main(["audit", "--retriever", "colbert"])


def test_a_broken_policy_file_exits_four(capsys, tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("retrieval: {}\n", encoding="utf-8")
    code = main(["audit", "--policy", str(path)])
    assert code == 4
    assert "usage error" in capsys.readouterr().err


def test_a_corpus_that_cannot_be_built_exits_three(capsys, tmp_path):
    """A policy that loads and describes a corpus the generator refuses."""
    path = tmp_path / "policy.yaml"
    path.write_text(
        "retrieval:\n  top_k: 1\n  sweep_k: [1]\n"
        "audit:\n  ceiling_floor: 0.95\n  material_gap: 0.02\n"
        "  unattributable_tolerance: 0.01\n  assumed_prevalence: 0.25\n"
        "corpus:\n  documents: 2\n  questions_per_document: 1\n  span_chars: [8, 9]\n"
        "encoder:\n  dimensions: 256\n  ngram: 2\n",
        encoding="utf-8",
    )
    code = main(
        ["audit", "--strategy", "sentence", "--size", "1", "--stride", "2", "--policy", str(path)]
    )
    assert code == 4
    assert "usage error" in capsys.readouterr().err


def test_the_audit_writes_html_when_asked(capsys, tmp_path):
    destination = tmp_path / "nested" / "report.html"
    main(["audit", "--html", str(destination), *SMALL])
    capsys.readouterr()
    assert destination.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_the_audit_writes_json_when_asked(capsys, tmp_path):
    destination = tmp_path / "audit.json"
    main(["audit", "--size", "200", "--stride", "200", "--json", str(destination), *SMALL])
    capsys.readouterr()
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["ceiling"]["ceiling"] < 1.0
    assert payload["metrics"]["gap"] > 0.0
    assert payload["exit_code"] == 1


def test_the_sweep_returns_zero_and_prints_the_table(capsys):
    code = main(["sweep", "--retrievers", "bm25", "--ks", "5", "--k", "5", *SMALL])
    output = capsys.readouterr().out
    assert code == 0
    assert "audited combinations" in output
    assert "bounds every retriever" in output


def test_the_sweep_writes_its_rows_and_its_page(capsys, tmp_path):
    main(
        [
            "sweep",
            "--retrievers",
            "bm25",
            "--ks",
            "5",
            "--k",
            "5",
            "--json",
            str(tmp_path / "sweep.json"),
            "--html",
            str(tmp_path / "sweep.html"),
            *SMALL,
        ]
    )
    capsys.readouterr()
    rows = json.loads((tmp_path / "sweep.json").read_text(encoding="utf-8"))
    assert rows
    assert (tmp_path / "sweep.html").exists()


def test_the_sweep_uses_the_policy_k_values_when_none_are_given(capsys, tmp_path):
    main(
        [
            "sweep",
            "--retrievers",
            "bm25",
            "--k",
            "5",
            "--json",
            str(tmp_path / "sweep.json"),
            *SMALL,
        ]
    )
    capsys.readouterr()
    rows = json.loads((tmp_path / "sweep.json").read_text(encoding="utf-8"))
    assert {row["k"] for row in rows} == {1, 5}


def test_the_parser_documents_every_exit_code():
    description = build_parser().description
    for code in ("0", "1", "2", "3", "4"):
        assert code in description


def test_the_module_entry_point_runs_from_a_clone():
    """`python -m chunkaudit` has to work before any install."""
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "chunkaudit", "audit", "--strategy", "document", *SMALL],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "containment ceiling" in completed.stdout
