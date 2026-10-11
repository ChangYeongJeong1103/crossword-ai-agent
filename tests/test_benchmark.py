"""Offline checks for benchmark statistics; no model calls."""
import json
import hashlib
from pathlib import Path

import pytest

from analyze_benchmark import (crosscheck_effect, incomplete, load, markdown, newcombe_paired, sign_test,
                               summarize, validate, wilson)
import run_benchmark as run_benchmark_module
from run_benchmark import CONFIGS, mismatch, run_one, settings_for

PUZZLE = Path(__file__).parents[1] / "data/synthetic/puzzles/mini_001.json"
GOLD = json.loads((PUZZLE.parents[1] / "gold" / PUZZLE.name).read_text())["answers"]


def row(config, puzzle, run, exact, **extra):
    return {"config": config, "puzzle": puzzle, "run": run, "exact": exact,
            "clue": 1.0 if exact else 0.5, "cell": 1.0, "tokens": 100, "calls": 10,
            "latency": 1.0, "rounds": 1, "termination": "complete_consistent_grid",
            "source": "s", "model": "m", "settings": "{}", "puzzle_hash": "h", "requests": 4,
            "clues_requested": 10, "splits": 0, **extra}


def test_sign_test_exact_p_values():
    assert sign_test(0, 0) == 1.0
    assert sign_test(0, 6) == pytest.approx(2 / 64)
    assert sign_test(3, 3) == 1.0


def test_comparison_uses_puzzles_not_runs_as_units():
    runs = [row(name, f"p{p}", k, exact)
            for p in range(10) for k in (1, 2)
            for name, exact in (("L3_full", True), ("L0_single_pass", p < 3))]
    summary = summarize(runs, expected_runs=2)
    full, single = summary["configs"]["L3_full"], summary["configs"]["L0_single_pass"]
    assert full["exact"]["mean"] == 1.0 and single["exact"]["mean"] == pytest.approx(0.3)
    assert single["false_accept"] == 14
    assert single["reliability"] == {"all": 3, "some": 0, "none": 7}
    assert single["clues_per_request"] == pytest.approx(2.5)
    paired = summary["paired_vs_reference"]["L0_single_pass"]
    # 7 puzzles worse, not 14 independent run pairs.
    assert (paired["puzzles"], paired["puzzles_worse"], paired["puzzles_better"]) == (10, 7, 0)
    assert paired["sign_test_p"] == pytest.approx(2 / 128)
    assert paired["delta_solved"] == pytest.approx(-0.7) and paired["ci_high"] < 0
    assert "L0_single_pass" in markdown(summary, {})


def test_validate_flags_mixing_and_missing_runs():
    good = [row("L3_full", "p0", k, True) for k in (1, 2)]
    assert validate(good, ["p0"], 2) == []
    assert any("missing" in p for p in validate(good, ["p0", "p1"], 2))
    assert any("source" in p for p in validate(good + [row("L3_full", "p1", 1, True, source="x")]))
    assert any("configs" in p for p in validate(good + [row("L3_full", "p1", 1, True, settings="x")]))
    assert any("outside" in p for p in validate(good, ["p9"], None))


def test_incomplete_matches_ask_retry_rule():
    record = {"ids": ["1A", "1D"], "mode": "fill"}
    assert not incomplete({**record, "text": '{"answers": {"1A": "X", "1D": ""}}'})
    assert incomplete({**record, "text": '{"answers": {"1A": "X"}}'})
    assert incomplete({**record, "text": ""})


def test_run_one_saves_comparable_evaluated_runs(tmp_path, monkeypatch):
    class Fake:
        model, calls = "fake", 0

        def __init__(self, model=None, max_calls=None):
            pass

        def complete(self, messages, max_tokens=None):
            ids = [c["id"] for c in json.loads(messages[1]["content"])["clues"]]
            return {"text": json.dumps({"answers": {k: GOLD[k] for k in ids}}),
                    "usage": {"total_tokens": 1}}

    monkeypatch.setattr("run_benchmark.Client", Fake)
    for name in CONFIGS:
        out = tmp_path / name / "mini_001" / "run1.json"
        run_one(name, PUZZLE, 1, out, "fake", "hash")
        saved = json.loads(out.read_text())
        assert saved["evaluation"]["exact_solve"]
        assert saved["config"]["max_calls"] == (800 if name == "L3_batch1" else 200)
        assert saved["runner_sha256"] == run_benchmark_module.runner_sha256()
        assert mismatch(out, name, PUZZLE, "fake", "hash") is None
        assert mismatch(out, name, PUZZLE, "fake", "other") == ["source_sha256"]
    other = "L3_full" if name != "L3_full" else "L0_single_pass"
    assert set(mismatch(out, other, PUZZLE, "fake", "hash")) == {"config", "config_name"}
    rows = load(tmp_path)
    assert {r["config"] for r in rows} == set(CONFIGS)
    assert validate(rows, ["mini_001"], 1) == []


def saved_run():
    return {"source_sha256": "hash", "model": "fake", "config": settings_for("L3_full")[1],
            "config_name": "L3_full", "puzzle_id": "mini_001", "run": 1,
            "puzzle_sha256": hashlib.sha256(PUZZLE.read_bytes()).hexdigest(),
            "answers": GOLD, "evaluation": {"exact_solve": True, "clue_accuracy": 1.0, "cell_accuracy": 1.0},
            "trace": [], "termination": "complete_consistent_grid", "calls": 1, "tokens": 1,
            "latency_seconds": 0.1}


@pytest.mark.parametrize("key", list(saved_run()))
def test_resume_rejects_missing_saved_fields(tmp_path, key):
    saved = saved_run()
    out = tmp_path / "run1.json"
    out.write_text(json.dumps(saved))
    assert mismatch(out, "L3_full", PUZZLE, "fake", "hash", 1) is None
    del saved[key]
    out.write_text(json.dumps(saved))
    assert mismatch(out, "L3_full", PUZZLE, "fake", "hash", 1)


@pytest.mark.parametrize("contents", ["{", "[]", "null", "{}"])
def test_resume_rejects_invalid_saved_results(tmp_path, contents):
    out = tmp_path / "run1.json"
    out.write_text(contents)
    assert mismatch(out, "L3_full", PUZZLE, "fake", "hash", 1)


def test_resume_rejects_wrong_run_identity(tmp_path):
    out = tmp_path / "run2.json"
    out.write_text(json.dumps(saved_run()))
    assert mismatch(out, "L3_full", PUZZLE, "fake", "hash", 2) == ["run"]


def test_validate_rejects_empty_duplicate_and_absent_configuration():
    good = row("L3_full", "p0", 1, True)
    assert validate([], ["p0"], 1)
    assert any("duplicate runs" in p for p in validate([good, good], ["p0"], 1))
    problems = validate([good], ["p0"], 1, ["L3_full", "L3_batch1"])
    assert any("L3_batch1: missing runs" in p for p in problems)
    assert validate([good], ["p0"], 0)
    assert any("outside" in p for p in validate([{**good, "run": 2}], ["p0"], 1))


def test_validate_rejects_missing_or_changed_puzzle_hashes():
    good = row("L3_full", "p0", 1, True)
    assert validate([good], ["p0"], 1, puzzle_hashes={"p0": "h"}) == []
    assert validate([{**good, "puzzle_hash": None}], ["p0"], 1)
    assert any("puzzle hash" in p for p in validate(
        [good, {**good, "run": 2, "puzzle_hash": "changed"}], ["p0"], 2))
    assert any("current puzzle" in p for p in validate([good], ["p0"], 1, puzzle_hashes={"p0": "changed"}))


def test_interim_summary_can_have_no_matching_reference_runs():
    runs = [row("L3_full", "p0", 1, True), row("L3_batch1", "p1", 1, False)]
    summary = summarize(runs)
    assert len(summary["configs"]) == 2
    assert summary["paired_vs_reference"] == {}


def test_puzzle_solved_means_at_least_three_of_five_exact_runs():
    runs = [row("L3_full", f"p{successes}", k, k <= successes)
            for successes in range(6) for k in range(1, 6)]
    # Even three successful runs are still an unfinished five-run experiment.
    runs += [row("L3_full", "pending", k, True) for k in range(1, 4)]
    summary = summarize(runs)
    stats = summary["configs"]["L3_full"]["solved"]
    assert (stats["count"], stats["puzzles"], stats["pending"], stats["mean"]) == (3, 6, 1, 0.5)
    for successes in range(6):
        assert summary["per_puzzle"][f"p{successes}"]["L3_full"]["puzzle_solved"] is (successes >= 3)
    assert summary["per_puzzle"]["pending"]["L3_full"]["puzzle_solved"] is None
    assert "Solved ≥3/5" in markdown(summary, {})


def test_config_comparisons_use_three_of_five_outcomes():
    runs = [row(name, "p0", k, k <= successes)
            for name, successes in (("L3_full", 3), ("L3_batch1", 5), ("L3_batch_all", 2))
            for k in range(1, 6)]
    summary = summarize(runs)
    tied = summary["paired_vs_reference"]["L3_batch1"]
    worse = summary["paired_vs_reference"]["L3_batch_all"]
    assert tied["delta_solved"] == 0 and tied["puzzles_tied"] == 1
    assert worse["delta_solved"] == -1 and worse["puzzles_worse"] == 1


def test_interim_paired_comparison_waits_for_five_runs_in_both_configs():
    runs = [row("L3_full", "p0", k, True) for k in range(1, 6)]
    runs += [row("L3_batch1", "p0", k, True) for k in range(1, 4)]
    summary = summarize(runs)
    assert summary["paired_vs_reference"] == {}
    assert summary["configs"]["L3_batch1"]["solved"]["mean"] is None
    assert "—" in markdown(summary, {})


def test_false_accept_counts_submitted_verified_grids_that_are_wrong():
    runs = [row("L3_full", "p0", 1, False, termination="budget_limit", submitted_verified=True),
            row("L3_full", "p1", 1, False, termination="budget_limit", submitted_verified=False),
            row("L3_full", "p2", 1, True, submitted_verified=True)]
    assert summarize(runs, expected_runs=1)["configs"]["L3_full"]["false_accept"] == 1


def test_validate_rejects_responses_from_another_model():
    good = row("L3_full", "p0", 1, True, served_models=["m"])
    assert validate([good], ["p0"], 1) == []
    other = row("L3_full", "p0", 1, True, served_models=["deepseek"])
    assert any("other than the requested" in p for p in validate([other], ["p0"], 1))


def test_crosscheck_effect_scores_the_check_against_gold():
    gold = {"1A": "ABC", "1D": "AXY"}
    run = lambda before, after, exact: {"trace": [{"phase": "crosscheck", "grid_before": before}],
                                       "answers": after, "evaluation": {"exact_solve": exact}}
    wrong = {"1A": "QBC", "1D": "QXY"}
    assert crosscheck_effect(run(wrong, gold, True), gold) == {"run": "fixed", "clues_fixed": 2, "clues_broken": 0}
    assert crosscheck_effect(run(gold, wrong, False), gold) == {"run": "broke", "clues_fixed": 0, "clues_broken": 2}
    assert crosscheck_effect(run(gold, gold, True), gold)["run"] == "unchanged"
    assert crosscheck_effect({"trace": [], "answers": gold, "evaluation": {"exact_solve": True}}, gold) is None


def test_markdown_reports_crosscheck_outcomes():
    effect = {"run": "fixed", "clues_fixed": 2, "clues_broken": 0}
    runs = [row("L3_full", "p0", 1, True, crosscheck_status="completed", crosscheck_effect=effect),
            row("L3_no_crosscheck", "p0", 1, False, crosscheck_status="disabled")]
    summary = summarize(runs, expected_runs=1)
    assert summary["configs"]["L3_full"]["crosscheck"]["runs"] == {"fixed": 1}
    table = markdown(summary, {})
    assert "| L3_full | 1 / 0 / 0 / 0 | — | 1 | 0 | 2 / 0 |" in table
    assert "| L3_no_crosscheck | 1 / 0" not in table


@pytest.mark.parametrize("text", ['{"answers": ["MAPLE"]}', '{"answers": "MAPLE"}', "no json", ""])
def test_memorization_probe_survives_malformed_answers(text):
    from scripts.probe_memorization import probe

    class Fake:
        def complete(self, messages, max_tokens=None):
            return {"text": text}

    result = probe(Fake(), PUZZLE)
    assert result["attempted"] == 0 and result["errors"]


def test_runner_reports_failed_runs_and_keeps_finished_ones(tmp_path, monkeypatch):
    import run_benchmark

    def flaky(name, puzzle_path, run, out, model, source):
        if name == "L3_full":
            raise RuntimeError("simulated crash")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}")
        return {"evaluation": {"exact_solve": True, "clue_accuracy": 1.0}, "tokens": 1,
                "termination": "complete_consistent_grid", "latency_seconds": 0.1}

    monkeypatch.setattr(run_benchmark, "run_one", flaky)
    monkeypatch.setattr("sys.argv", ["run_benchmark.py", "--puzzles", str(PUZZLE.parent), "--runs", "1",
                                     "--configs", "L3_full", "L0_single_pass", "--out", str(tmp_path)])
    with pytest.raises(SystemExit, match="1 of 2 runs failed"):
        run_benchmark.main()
    assert (tmp_path / "L0_single_pass" / "mini_001" / "run1.json").exists()
    assert not (tmp_path / "L3_full").exists()


def test_infrastructure_errors_block_analysis_until_attempts_are_used():
    clean = row("L3_full", "p0", 1, True, infra_errors=0)
    assert validate([clean], ["p0"], 1) == []
    broken = row("L3_full", "p0", 1, True, infra_errors=2)
    assert any("not yet rerun" in p for p in validate([broken], ["p0"], 1))
    assert any("not yet rerun" in p for p in validate([broken], ["p0"], 1, archived={("L3_full", "p0", 1): 1}))
    # Third attempt still affected: kept and reported, not blocking.
    assert validate([broken], ["p0"], 1, archived={("L3_full", "p0", 1): 2}) == []


def test_load_counts_only_transport_failures_as_infrastructure_errors(tmp_path):
    responses = [{"error": "Token Factory HTTP 503."}, {"error": "Invalid output: substring not found"},
                 {"error": "Call or reported-token budget reached.", "budget_exhausted": True}, {"text": "{}"}]
    run = {"config_name": "L3_full", "puzzle_id": "p0", "run": 1, "tokens": 1, "calls": 1,
           "latency_seconds": 1, "termination": "budget_limit", "source_sha256": "s", "model": "m",
           "config": {}, "answers": {}, "trace": [{"phase": "fill", "responses": responses}],
           "evaluation": {"exact_solve": False, "clue_accuracy": 0.0, "cell_accuracy": 0.0}}
    (tmp_path / "L3_full" / "p0").mkdir(parents=True)
    (tmp_path / "L3_full" / "p0" / "run1.json").write_text(json.dumps(run))
    assert load(tmp_path)[0]["infra_errors"] == 1


def test_rerun_archives_infrastructure_errors_for_at_most_three_attempts(tmp_path):
    from run_benchmark import rerun_infra_errors

    jobs = [("L3_full", PUZZLE, 1), ("L3_full", PUZZLE, 2)]
    output = lambda name, path, run: tmp_path / "runs" / name / path.stem / f"run{run}.json"
    archive = tmp_path / "runs_reruns"
    broken = {"tokens": 7, "trace": [{"responses": [{"error": "Token Factory HTTP 503."}]}]}
    clean = {"tokens": 5, "trace": [{"responses": [{"error": "Invalid output: no JSON"}]}]}

    def save(run, result):
        output("L3_full", PUZZLE, run).parent.mkdir(parents=True, exist_ok=True)
        output("L3_full", PUZZLE, run).write_text(json.dumps(result))

    for attempt in (1, 2):  # Attempts 1 and 2 hit infrastructure errors and are archived.
        save(1, broken)
        save(2, clean)  # Model errors are not infrastructure errors: never rerun.
        assert rerun_infra_errors(jobs, output, archive) == 1
        assert not output("L3_full", PUZZLE, 1).exists() and output("L3_full", PUZZLE, 2).exists()
    save(1, broken)  # The third attempt is the last one allowed: kept.
    assert rerun_infra_errors(jobs, output, archive) == 0
    ledger = json.loads((archive / "ledger.json").read_text())
    assert [(e["run"], e["attempt"], e["tokens"]) for e in ledger] == [(1, 1, 7), (1, 2, 7)]
    assert (archive / "L3_full" / "mini_001" / "run1_attempt2.json").exists()


def test_wilson_interval_matches_known_values():
    assert wilson(10, 10)[1] == pytest.approx(0.7225, abs=1e-4)
    assert wilson(0, 10)[2] == pytest.approx(0.2775, abs=1e-4)
    p, low, high = wilson(43, 50)
    assert p == 0.86 and low == pytest.approx(0.7384, abs=1e-3) and high == pytest.approx(0.9305, abs=1e-3)
    assert wilson(0, 0) == (None, None, None)


def test_newcombe_paired_interval_behaves():
    # All tied and all solved: no observed difference, but the interval is not degenerate.
    d, low, high = newcombe_paired(10, 0, 0, 0)
    assert d == 0 and low == pytest.approx(-0.2775, abs=1e-4) and high == pytest.approx(0.2775, abs=1e-4)
    d, low, high = newcombe_paired(3, 7, 0, 0)  # The config loses 7 of 10 puzzles.
    assert d == pytest.approx(-0.7) and -1 <= low < d < high < 0
    d, low, high = newcombe_paired(20, 1, 6, 23)
    assert d == pytest.approx(0.1) and low < d < high and low > -0.1
    assert newcombe_paired(0, 0, 0, 0) == (None, None, None)


def test_summary_reports_solved_rate_with_wilson_and_secondary_run_comparison():
    runs = [row(name, f"p{p}", k, exact)
            for p in range(10) for k in range(1, 6)
            for name, exact in (("L3_full", True), ("L3_no_crosscheck", k != 1 or p > 4))]
    summary = summarize(runs)
    assert summary["configs"]["L3_full"]["solved"]["ci_low"] == pytest.approx(0.7225, abs=1e-4)
    primary = summary["paired_vs_reference"]["L3_no_crosscheck"]
    assert primary["puzzles_tied"] == 10 and primary["ci_low"] < 0 < primary["ci_high"]
    secondary = summary["paired_runs_vs_reference"]["L3_no_crosscheck"]
    assert secondary["delta_exact"] == pytest.approx(-0.1) and secondary["puzzles_lower"] == 5
    table = markdown(summary, {})
    assert "95% Wilson CI" in table and "Exact McNemar p" in table and "(secondary)" in table


@pytest.mark.parametrize("e, f, g, h, low, high", [
    (36, 12, 2, 0, 0.0569, 0.3404), (20, 12, 2, 16, 0.0562, 0.3292), (18, 12, 2, 18, 0.0562, 0.3290),
    (36, 14, 0, 0, 0.1528, 0.4167), (35, 14, 0, 1, 0.1461, 0.4175), (18, 14, 0, 18, 0.1441, 0.3963)])
def test_newcombe_matches_method_10_in_the_original_paper(e, f, g, h, low, high):
    # Newcombe (1998), Statistics in Medicine 17:2635-2650, Table III, method 10, for (f - g) / n.
    d, lower, upper = newcombe_paired(e, g, f, h)
    assert d == pytest.approx((f - g) / (e + f + g + h))
    assert (lower, upper) == (pytest.approx(low, abs=6e-5), pytest.approx(high, abs=6e-5))
