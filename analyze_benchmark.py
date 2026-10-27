"""Aggregate benchmark runs into summary tables with puzzle-level uncertainty.

Runs of the same puzzle are correlated, so every interval resamples whole
puzzles (cluster bootstrap) and every test treats the puzzle as the unit:
A puzzle is solved when a strict majority of its scheduled runs solve it exactly
(at least 3 of the default 5 runs). Config comparisons against L3_full use these
puzzle outcomes, with a paired bootstrap CI and an exact sign test over puzzles.

Before summarizing, runs are checked for one source hash, model and config per
configuration, and for missing runs against the selection manifest.
"""
import argparse
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

from run_benchmark import MAX_ATTEMPTS

ROOT = Path(__file__).parent
REFERENCE = "L3_full"
ORDER = ["L0_single_pass", "L1_fill_loop", "L2_fill_repair", "L3_full", "L3_no_crosscheck",
         "L3_batch1", "L3_batch_all"]


def incomplete(record):
    """True when a model response did not answer every requested ID (as ask() judges it)."""
    try:
        text = record["text"].strip()
        values = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]["answers"]
        return not isinstance(values, dict) or any(k not in values for k in record["ids"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return True


def crosscheck_effect(r, gold):
    """Compare the grid before crosscheck with the submitted grid, against gold."""
    check = next((t for t in r["trace"] if t["phase"] == "crosscheck"), None)
    if check is None or gold is None:
        return None
    before, after = check["grid_before"], r["answers"]
    was, now = before == gold, r["evaluation"]["exact_solve"]
    return {"run": "fixed" if now and not was else "broke" if was and not now
            else "changed" if before != after else "unchanged",
            "clues_fixed": sum(before.get(k) != v and after.get(k) == v for k, v in gold.items()),
            "clues_broken": sum(before.get(k) == v and after.get(k) != v for k, v in gold.items())}


def crosscheck_coverage(r):
    """(clues answered, clues with a non-blank answer, all clues) in the crosscheck pass."""
    check = next((t for t in r["trace"] if t["phase"] == "crosscheck"), None)
    if check is None:
        return None
    clues = set(check["grid_before"])
    answered = {k for x in check["responses"] if x.get("mode") == "fill" for k in x.get("answered", ())}
    return len(clues & answered), len(clues & set(check["blind_answers"])), len(clues)


def load(folder, golds=None):
    runs = []
    for path in sorted(folder.glob("*/*/run*.json")):
        r = json.loads(path.read_text())
        e = r["evaluation"]
        responses = [x for t in r["trace"] for x in t["responses"]]
        requests = [x for x in responses if not x.get("budget_exhausted")]
        # Historical runs used the solver model for review too.
        reviewer = r.get("review_model", r["model"] if r["config"].get("review", True) else None)
        model_errors = []
        for x in responses:
            expected = reviewer if x.get("mode") == "review" else r["model"]
            if any(x.get(key) and x[key] != expected for key in ("requested_model", "served_model")):
                model_errors.append({"mode": x.get("mode"), "expected": expected,
                                     "requested": x.get("requested_model"), "served": x.get("served_model")})
        runs.append({"config": r["config_name"], "puzzle": r["puzzle_id"], "run": r["run"],
                     "exact": e["exact_solve"], "clue": e["clue_accuracy"], "cell": e["cell_accuracy"],
                     "tokens": r["tokens"], "calls": r["calls"], "latency": r["latency_seconds"],
                     "rounds": len(r["trace"]), "termination": r["termination"],
                     "source": r["source_sha256"], "model": r["model"],
                     "review_model": reviewer, "model_errors": model_errors,
                     "puzzle_hash": r.get("puzzle_sha256"),
                     "settings": json.dumps(r["config"], sort_keys=True),
                     "requests": len(requests),
                     "clues_requested": sum(len(x.get("ids", [])) for x in requests),
                     # ask() splits a multi-clue request whenever its response is incomplete.
                     "splits": sum("mode" in x and len(x["ids"]) > 1 and incomplete(x) for x in requests),
                     # Runs saved before these fields existed fall back to the termination label.
                     "submitted_verified": r.get("submitted_verified",
                                                 r["termination"] == "complete_consistent_grid"),
                     "crosscheck_status": r.get("crosscheck_status"),
                     "crosscheck_effect": crosscheck_effect(r, (golds or {}).get(r["puzzle_id"])),
                     "crosscheck_coverage": crosscheck_coverage(r),
                     "served_models": sorted({x["served_model"] for x in responses if x.get("served_model")}),
                     # Requests that still failed after the client's HTTP retries (not model output).
                     "infra_errors": sum((x.get("error") or "").startswith("Token Factory") for x in responses)})
    return runs


def validate(runs, puzzles=None, expected_runs=None, expected_configs=None, puzzle_hashes=None, archived=None):
    """Return problems that would make configurations incomparable or incomplete."""
    problems = []
    if not runs:
        return ["no completed runs"]
    if expected_runs is not None and expected_runs < 1:
        return ["expected_runs must be positive"]
    if puzzles is not None and (not puzzles or len(set(puzzles)) != len(puzzles)):
        return ["expected puzzle set is empty or contains duplicate IDs"]
    for r in runs:
        missing = [key for key in ("config", "puzzle", "source", "model", "settings", "puzzle_hash")
                   if not isinstance(r.get(key), str) or not r[key]]
        if missing or type(r.get("run")) is not int or r["run"] < 1:
            problems.append(f"invalid run metadata: missing {missing} or invalid run index")
    if problems:
        return problems
    duplicates = [key for key, n in Counter((r["config"], r["puzzle"], r["run"]) for r in runs).items() if n > 1]
    if duplicates:
        problems.append(f"duplicate runs: {duplicates[:3]}")
    present = {r["config"] for r in runs}
    expected = set(expected_configs) if expected_configs is not None else present
    unknown = present - set(ORDER)
    if unknown or present - expected:
        problems.append(f"unexpected configurations: {sorted(unknown | (present - expected))}")
    for name in sorted(expected - present):
        problems.append(f"{name}: missing runs (entire configuration)")
    for puzzle in {r["puzzle"] for r in runs}:
        hashes = {r["puzzle_hash"] for r in runs if r["puzzle"] == puzzle}
        if len(hashes) > 1:
            problems.append(f"{puzzle}: runs mix several puzzle hashes")
        if puzzle_hashes is not None and puzzle in puzzle_hashes and hashes != {puzzle_hashes[puzzle]}:
            problems.append(f"{puzzle}: saved puzzle hash differs from the current puzzle")
    # Runs with infrastructure errors must have used their attempts; the last attempt is kept.
    archived = archived or {}
    pending = sorted(key for r in runs if r.get("infra_errors")
                     and archived.get(key := (r["config"], r["puzzle"], r["run"]), 0) + 1 < MAX_ATTEMPTS)
    if pending:
        problems.append(f"{len(pending)} runs have infrastructure errors not yet rerun under the protocol "
                        f"(run_benchmark.py --rerun-infra-errors): {pending[:3]}")
    served = {m for r in runs for m in r.get("served_models", [])
              if m not in {r["model"], r.get("review_model")}}
    if served:
        problems.append(f"responses served by a model other than the requested one: {sorted(served)}")
    if any(r.get("model_errors") for r in runs):
        problems.append("responses requested or served by a model other than the requested model for their phase")
    for key in ("source", "model"):
        if len({r[key] for r in runs}) > 1:
            problems.append(f"runs mix several {key} values: {sorted({r[key] for r in runs})}")
    for name in {r["config"] for r in runs}:
        rows = [r for r in runs if r["config"] == name]
        if len({r["settings"] for r in rows}) > 1:
            problems.append(f"{name}: runs mix several configs")
        if len({r.get("review_model", r["model"]) for r in rows}) > 1:
            problems.append(f"{name}: runs mix several review models")
        have = {(r["puzzle"], r["run"]) for r in rows}
        if expected_runs is not None and any(k > expected_runs for _, k in have):
            problems.append(f"{name}: run indices outside 1..{expected_runs}")
        if puzzles is not None:
            extra = sorted({p for p, _ in have} - set(puzzles))
            if extra:
                problems.append(f"{name}: puzzles outside the selected set: {extra}")
            if expected_runs:
                missing = [(p, k) for p in puzzles for k in range(1, expected_runs + 1) if (p, k) not in have]
                if missing:
                    problems.append(f"{name}: {len(missing)} missing runs, e.g. {missing[:3]}")
    return problems


def by_puzzle(rows, key):
    groups = defaultdict(list)
    for r in rows:
        groups[r["puzzle"]].append(float(r[key]))
    return {p: statistics.fmean(v) for p, v in groups.items()}


def bootstrap(values, rng, n=10000):
    """Mean of per-puzzle values with a 95% percentile CI over resampled puzzles."""
    values = list(values)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(n))
    return statistics.fmean(values), means[int(0.025 * n)], means[int(0.975 * n) - 1]


Z95 = 1.959963984540054


def wilson(successes, n, z=Z95):
    """Proportion with its Wilson score 95% interval."""
    if n == 0:
        return None, None, None
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return p, max(0.0, centre - half), min(1.0, centre + half)


def newcombe_paired(both, reference_only, config_only, neither, z=Z95):
    """Difference (config rate - reference rate) on paired binary outcomes with a 95% CI by
    Newcombe's (1998) method 10: Wilson score intervals combined with a continuity-corrected
    estimate of the correlation between the paired outcomes."""
    n = both + reference_only + config_only + neither
    if n == 0:
        return None, None, None
    p_ref, l_ref, u_ref = wilson(both + reference_only, n, z)
    p_cfg, l_cfg, u_cfg = wilson(both + config_only, n, z)
    margins = (both + reference_only) * (config_only + neither) * (both + config_only) * (reference_only + neither)
    numerator = both * neither - reference_only * config_only
    if numerator > 0:  # Method 10's continuity correction; without it this is method 8.
        numerator = max(numerator - n / 2, 0)
    phi = numerator / math.sqrt(margins) if margins else 0.0
    delta = math.sqrt(max(0.0, (p_cfg - l_cfg) ** 2 - 2 * phi * (p_cfg - l_cfg) * (u_ref - p_ref) + (u_ref - p_ref) ** 2))
    epsilon = math.sqrt(max(0.0, (u_cfg - p_cfg) ** 2 - 2 * phi * (u_cfg - p_cfg) * (p_ref - l_ref) + (p_ref - l_ref) ** 2))
    d = p_cfg - p_ref
    return d, max(-1.0, d - delta), min(1.0, d + epsilon)


def sign_test(worse, better):
    """Exact two-sided sign test over puzzles whose mean success differs."""
    n = worse + better
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(min(worse, better) + 1)) / 2 ** n)


def percentile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def summarize(runs, seed=0, expected_runs=5):
    if expected_runs < 1:
        raise ValueError("expected_runs must be positive")
    threshold = expected_runs // 2 + 1
    rng = random.Random(seed)
    configs = [c for c in ORDER if any(r["config"] == c for r in runs)]
    out = {"configs": {}, "paired_vs_reference": {}, "per_puzzle": defaultdict(dict),
           "solve_rule": {"runs": expected_runs, "min_exact": threshold, "incomplete": "excluded"}}
    outcomes = {}
    for name in configs:
        rows = [r for r in runs if r["config"] == name]
        solved = Counter()
        for r in rows:
            solved[r["puzzle"]] += r["exact"]
        attempts = Counter(r["puzzle"] for r in rows)
        stats = {"runs": len(rows), "puzzles": len(attempts)}
        stats.update(model=rows[0]["model"], review_model=rows[0].get("review_model", rows[0]["model"]))
        outcomes[name] = {p: solved[p] >= threshold for p in attempts
                          if attempts[p] == expected_runs
                          and {r["run"] for r in rows if r["puzzle"] == p} == set(range(1, expected_runs + 1))}
        majority = outcomes[name]
        stats["solved"] = dict(zip(("mean", "ci_low", "ci_high"), wilson(sum(majority.values()), len(majority))))
        stats["solved"].update(count=sum(majority.values()), puzzles=len(majority),
                               pending=len(attempts) - len(majority))
        for key in ("exact", "clue", "cell"):
            stats[key] = dict(zip(("mean", "ci_low", "ci_high"), bootstrap(by_puzzle(rows, key).values(), rng)))
        tokens = [r["tokens"] for r in rows]
        stats.update(
            # A wrong grid the controller itself had accepted (verified) and submitted.
            false_accept=sum(r.get("submitted_verified", r["termination"] == "complete_consistent_grid")
                             and not r["exact"] for r in rows),
            crosscheck={"status": dict(Counter(r.get("crosscheck_status") for r in rows)),
                        "runs": dict(Counter(x["run"] for r in rows if (x := r.get("crosscheck_effect")))),
                        "clues_fixed": sum(x["clues_fixed"] for r in rows if (x := r.get("crosscheck_effect"))),
                        "clues_broken": sum(x["clues_broken"] for r in rows if (x := r.get("crosscheck_effect"))),
                        # Share of clues the crosscheck pass got a response for / a non-blank answer for.
                        "coverage": coverage([r.get("crosscheck_coverage") for r in rows])},
            verified_submissions=sum(r.get("submitted_verified", False) for r in rows),
            termination_of_verified=dict(Counter(r["termination"] for r in rows if r.get("submitted_verified"))),
            tokens_total=sum(tokens),
            tokens_median=statistics.median(tokens), tokens_p90=percentile(tokens, 0.9),
            tokens_per_exact=sum(tokens) / exact if (exact := sum(r["exact"] for r in rows)) else None,
            calls_median=statistics.median(r["calls"] for r in rows),
            requests_median=statistics.median(r["requests"] for r in rows),
            clues_per_request=sum(r["clues_requested"] for r in rows) / max(1, sum(r["requests"] for r in rows)),
            splits_per_run=statistics.fmean(r["splits"] for r in rows),
            latency_median=statistics.median(r["latency"] for r in rows),
            termination=dict(Counter(r["termination"] for r in rows)),
            reliability={"all": sum(solved[p] == attempts[p] for p in attempts),
                         "some": sum(0 < solved[p] < attempts[p] for p in attempts),
                         "none": sum(solved[p] == 0 for p in attempts)})
        out["configs"][name] = stats
        for p in attempts:
            out["per_puzzle"][p][name] = {"solved": solved[p], "runs": attempts[p],
                                          "puzzle_solved": majority.get(p),
                                          "tokens_median": statistics.median(r["tokens"] for r in rows if r["puzzle"] == p)}
    ref = outcomes.get(REFERENCE, {})
    exact_rate = {name: by_puzzle([r for r in runs if r["config"] == name], "exact") for name in configs}
    out["paired_runs_vs_reference"] = {}
    for name in configs:
        if name == REFERENCE or not ref:
            continue
        common = sorted(ref.keys() & outcomes[name].keys())
        if not common:  # Compare only puzzles with all scheduled runs in both configs.
            continue
        # Primary: puzzle outcomes (solved or not), exact McNemar test and Newcombe CI.
        cells = Counter((ref[p], outcomes[name][p]) for p in common)
        both, worse, better, neither = cells[(True, True)], cells[(True, False)], cells[(False, True)], cells[(False, False)]
        delta, low, high = newcombe_paired(both, worse, better, neither)
        out["paired_vs_reference"][name] = {"puzzles": len(common), "delta_solved": delta, "ci_low": low,
                                            "ci_high": high, "puzzles_worse": worse, "puzzles_better": better,
                                            "puzzles_tied": both + neither, "sign_test_p": sign_test(worse, better)}
        # Secondary: per-puzzle difference in exact-solve rate per run, puzzles resampled with their runs.
        diffs = [exact_rate[name][p] - exact_rate[REFERENCE][p] for p in common]
        mean, low, high = bootstrap(diffs, rng)
        lower, higher = sum(d < 0 for d in diffs), sum(d > 0 for d in diffs)
        out["paired_runs_vs_reference"][name] = {"puzzles": len(common), "delta_exact": mean, "ci_low": low,
                                                 "ci_high": high, "puzzles_lower": lower, "puzzles_higher": higher,
                                                 "puzzles_tied": len(diffs) - lower - higher,
                                                 "sign_test_p": sign_test(lower, higher)}
    out["per_puzzle"] = dict(out["per_puzzle"])
    return out


def coverage(items):
    items = [x for x in items if x]
    total = sum(x[2] for x in items)
    return {"answered": sum(x[0] for x in items) / total, "second_opinion": sum(x[1] for x in items) / total} \
        if total else None


def probe_summary(folder):
    rows = [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]
    sets = defaultdict(lambda: {"puzzles": 0, "slots": 0, "attempted": 0, "correct": 0})
    for r in rows:
        s = sets[r["set"]]
        s["puzzles"] += 1
        for key in ("slots", "attempted", "correct"):
            s[key] += r[key]
    return dict(sets)


def markdown(summary, probe):
    pct = lambda s: "—" if s["mean"] is None else f"{s['mean']:.1%} [{s['ci_low']:.1%}, {s['ci_high']:.1%}]"
    rule = summary["solve_rule"]
    lines = [f"Puzzle solved: at least {rule['min_exact']} exact solves in {rule['runs']} runs. "
             "Puzzles with unfinished runs are excluded from the solved rate and paired comparisons.", ""]
    lines += ["| Config | Solver model | Review model |", "|---|---|---|"]
    for name, s in summary["configs"].items():
        lines.append(f"| {name} | {s['model']} | {s['review_model'] or 'disabled'} |")
    lines += ["",
             f"| Config | Runs | Completed / pending puzzles | Solved ≥{rule['min_exact']}/{rule['runs']} [95% Wilson CI] "
             "| Exact solve / run [95% cluster CI] | Clue accuracy | Cell accuracy | False accept "
             "| Tokens median / p90 | Tokens per exact | HTTP calls median | Latency median |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in summary["configs"].items():
        per_exact = "—" if s["tokens_per_exact"] is None else f"{s['tokens_per_exact']:,.0f}"
        solved = s["solved"]
        lines.append(f"| {name} | {s['runs']} | {solved['puzzles']} / {solved['pending']} "
                     f"| {solved['count']}/{solved['puzzles']}: {pct(solved)} "
                     f"| {pct(s['exact'])} | {pct(s['clue'])} | {pct(s['cell'])} "
                     f"| {s['false_accept']} | {s['tokens_median']:,.0f} / {s['tokens_p90']:,.0f} "
                     f"| {per_exact} | {s['calls_median']:.0f} | {s['latency_median']:.0f}s |")
    lines += ["", "| Config | Tokens total | Requests per run (median) | Clues per request (mean) "
              "| Split fallbacks per run (mean) | Verified grid submitted (termination) |", "|---|---|---|---|---|---|"]
    for name, s in summary["configs"].items():
        ends = ", ".join(f"{k} {v}" for k, v in sorted(s["termination_of_verified"].items()))
        lines.append(f"| {name} | {s['tokens_total']:,} | {s['requests_median']:.0f} | {s['clues_per_request']:.2f} "
                     f"| {s['splits_per_run']:.1f} | {s['verified_submissions']} ({ends or '—'}) |")
    lines += ["", f"| Config vs {REFERENCE} | Puzzles | Δ solved-puzzle rate [95% Newcombe CI] | Puzzles worse "
              "| Puzzles better | Tied | Exact McNemar p |", "|---|---|---|---|---|---|---|"]
    for name, s in summary["paired_vs_reference"].items():
        lines.append(f"| {name} | {s['puzzles']} | {s['delta_solved']:+.1%} [{s['ci_low']:+.1%}, {s['ci_high']:+.1%}] "
                     f"| {s['puzzles_worse']} | {s['puzzles_better']} | {s['puzzles_tied']} "
                     f"| {s['sign_test_p']:.3g} |")
    if summary.get("paired_runs_vs_reference"):
        lines += ["", f"| Config vs {REFERENCE} (secondary) | Puzzles | Δ exact solves per run [95% cluster CI] "
                  "| Puzzles lower | Puzzles higher | Tied | Sign test p |", "|---|---|---|---|---|---|---|"]
        for name, s in summary["paired_runs_vs_reference"].items():
            lines.append(f"| {name} | {s['puzzles']} | {s['delta_exact']:+.1%} [{s['ci_low']:+.1%}, {s['ci_high']:+.1%}] "
                         f"| {s['puzzles_lower']} | {s['puzzles_higher']} | {s['puzzles_tied']} "
                         f"| {s['sign_test_p']:.3g} |")
    checked = {name: s["crosscheck"] for name, s in summary["configs"].items()
               if set(s["crosscheck"]["status"]) - {"disabled", None}}
    if checked:
        lines += ["", "| Config | Crosscheck completed / incomplete / skipped / not reached "
                  "| Clues answered / with a second opinion | Runs fixed (wrong → exact) "
                  "| Runs broken (exact → wrong) | Clues fixed / broken |", "|---|---|---|---|---|---|"]
        for name, c in checked.items():
            s, cov = c["status"], c.get("coverage")
            share = f"{cov['answered']:.1%} / {cov['second_opinion']:.1%}" if cov else "—"
            lines.append(f"| {name} | {s.get('completed', 0)} / {s.get('incomplete', 0)} / {s.get('skipped', 0)} "
                         f"/ {s.get('not_reached', 0)} | {share} | {c['runs'].get('fixed', 0)} "
                         f"| {c['runs'].get('broke', 0)} | {c['clues_fixed']} / {c['clues_broken']} |")
    lines += ["", "| Config | Puzzles solved in every run | In some runs | In no run |", "|---|---|---|---|"]
    for name, s in summary["configs"].items():
        r = s["reliability"]
        lines.append(f"| {name} | {r['all']} | {r['some']} | {r['none']} |")
    a = summary.get("attempts")
    if a:
        lines += ["", f"Evaluated runs: {a['evaluated_runs']:,}. Attempts archived for infrastructure errors: "
                      f"{a['archived_attempts']:,}. Runs kept with residual infrastructure errors: "
                      f"{len(a['residual_infra_error_runs'])}. Tokens across all attempts: {a['tokens_all_attempts']:,}."]
    if probe:
        lines += ["", "| Memorization probe set | Puzzles | Slots | Attempted | Recalled correctly |",
                  "|---|---|---|---|---|"]
        for name, s in probe.items():
            lines.append(f"| {name} | {s['puzzles']} | {s['slots']} | {s['attempted']} "
                         f"| {s['correct']} ({s['correct'] / s['slots']:.1%}) |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=ROOT / "results/benchmark/glm_review/runs")
    parser.add_argument("--probe", type=Path, help="optional probe results from the same model setup")
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "data/benchmark/crosshare_heldout/selection_manifest.json")
    parser.add_argument("--puzzle-dirs", type=Path, nargs="+",
                        help="define the expected puzzles by folders instead of the manifest")
    parser.add_argument("--configs", nargs="+", choices=ORDER, help="summarize only these configurations")
    parser.add_argument("--expected-runs", type=int, default=5)
    parser.add_argument("--allow-incomplete", action="store_true",
                        help="summarize despite missing runs (interim look); mixing is never allowed")
    parser.add_argument("--out", type=Path, default=ROOT / "results/benchmark/glm_review")
    args = parser.parse_args()
    if args.expected_runs < 1:
        parser.error("expected-runs must be positive")
    if args.puzzle_dirs:
        files = sorted(p for folder in args.puzzle_dirs for p in folder.glob("*.json"))
        puzzles = sorted(p.stem for p in files)
    else:
        puzzles = [s["puzzle_id"] for s in json.loads(args.manifest.read_text())["selected"]]
        files = [args.manifest.parent / "puzzles" / f"{p}.json" for p in puzzles]
    puzzle_hashes = {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.exists()}
    # Gold is read here only to score what crosscheck changed, after every run has finished.
    golds = {p.stem: json.loads(g.read_text())["answers"] for p in files
             if (g := p.parents[1] / "gold" / p.name).exists()}
    runs = [r for r in load(args.runs, golds) if not args.configs or r["config"] in args.configs]
    ledger_path = args.runs.parent / f"{args.runs.name}_reruns" / "ledger.json"
    ledger = [e for e in (json.loads(ledger_path.read_text()) if ledger_path.exists() else [])
              if not args.configs or e["config"] in args.configs]
    archived = Counter((e["config"], e["puzzle_id"], e["run"]) for e in ledger)
    problems = validate(runs, puzzles, args.expected_runs, args.configs or ORDER, puzzle_hashes, archived)
    for problem in problems:
        print("CHECK:", problem)
    fatal = [p for p in problems if not ("missing runs" in p and args.allow_incomplete)]
    if fatal:
        raise SystemExit("Runs are not comparable or complete; see CHECK lines above.")
    summary = summarize(runs, expected_runs=args.expected_runs)
    summary["checks"] = problems
    # Performance uses the kept attempt of each run; cost counts every attempt.
    summary["attempts"] = {
        "evaluated_runs": len(runs), "archived_attempts": len(ledger),
        "residual_infra_error_runs": sorted([r["config"], r["puzzle"], r["run"]] for r in runs if r["infra_errors"]),
        "tokens_all_attempts": sum(r["tokens"] for r in runs) + sum(e["tokens"] for e in ledger)}
    probe = probe_summary(args.probe) if args.probe and args.probe.exists() else {}
    summary["memorization_probe"] = probe
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    table = markdown(summary, probe)
    (args.out / "summary.md").write_text(table)
    print(table)


if __name__ == "__main__":
    main()
