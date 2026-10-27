"""Validate and compare the two reviewer cohorts without additional model calls."""
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from analyze_benchmark import bootstrap, load, newcombe_paired, sign_test, summarize, validate
from run_pilot import OUT, PUZZLES, REPEATS, REVIEWERS

PRICES = {
    "zai-org/GLM-5.3-Flash": {"input": 0.15, "output": 0.50},
    "nvidia/Nemotron-3.5-Super-VL": {"input": 0.30, "output": 0.90},
}
PRICE_SOURCES = [
    "https://nebius.com/services/token-factory/models/glm-models-inference",
    "https://nebius.com/blog/posts/three-new-open-weight-models-from-us-companies-give-builders-more-choice",
]


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    expected = [p.stem for p in PUZZLES]
    hashes = {p["puzzle_id"]: p["sha256"] for p in protocol["puzzles"]}
    result = {"scope": "Selected public development puzzles; diagnostic pilot, not held-out evaluation.",
              "puzzles": expected, "runs_per_puzzle": REPEATS, "cohorts": {},
              "price_usd_per_million_tokens": PRICES, "price_sources": PRICE_SOURCES,
              "cost_basis": "Estimated uncached list price, including reported reasoning output tokens; excludes discounts.",
              "price_checked_on": "2026-10-26"}
    for cohort, reviewer in REVIEWERS.items():
        folder = OUT / cohort / "runs"
        rows = load(folder)
        problems = validate(rows, expected, REPEATS, ["L3_full"], hashes)
        problems += ["source or reviewer differs from protocol"] if any(
            r["source"] != protocol["source_sha256"] or r["review_model"] != reviewer for r in rows) else []
        if problems:
            raise SystemExit(f"{cohort}: {problems}")
        summary = summarize(rows, expected_runs=REPEATS)
        stats = summary["configs"]["L3_full"]
        stats["exact_count"] = sum(r["exact"] for r in rows)
        stats["per_puzzle"] = {p: summary["per_puzzle"][p]["L3_full"] for p in expected}
        costs, by_model = [], {}
        review_tokens, review_seconds, truncated, retries = [], [], 0, 0
        for path in sorted(folder.glob("*/*/run*.json")):
            raw = json.loads(path.read_text())
            if raw["runner_sha256"] != protocol["runner_sha256"]:
                raise SystemExit(f"Runner differs from protocol: {path}")
            cost, review_token_count, review_time, previous_time = 0.0, 0, 0.0, 0.0
            for step in raw["trace"]:
                if step["phase"] == "review":
                    review_time += step["latency_seconds"] - previous_time
                previous_time = step["latency_seconds"]
                for response in step["responses"]:
                    if not response.get("usage"):
                        continue
                    model = response["served_model"]
                    usage = response["usage"]
                    retries += max(0, response.get("http_attempts", 1) - 1)
                    if response.get("mode") == "review":
                        review_token_count += usage.get("total_tokens", 0)
                        truncated += response.get("finish_reason") == "length"
                    item = by_model.setdefault(model, {"input_tokens": 0, "output_tokens": 0, "responses": 0})
                    item["input_tokens"] += usage["prompt_tokens"]
                    item["output_tokens"] += usage["completion_tokens"]
                    item["responses"] += 1
                    cost += (usage["prompt_tokens"] * PRICES[model]["input"]
                             + usage["completion_tokens"] * PRICES[model]["output"]) / 1_000_000
            stats["per_puzzle"][raw["puzzle_id"]].update(
                latency_seconds=raw["latency_seconds"], estimated_cost_usd=cost,
                review_tokens=review_token_count, review_round_seconds=review_time,
                review_reached=any(t["phase"] == "review" for t in raw["trace"]),
                termination=raw["termination"])
            costs.append(cost)
            review_tokens.append(review_token_count)
            review_seconds.append(review_time)
        stats.update(estimated_cost_usd_total=sum(costs), estimated_cost_usd_median=statistics.median(costs),
                     review_tokens_median=statistics.median(review_tokens),
                     review_round_seconds_median=statistics.median(review_seconds),
                     review_length_limited_responses=truncated, http_retry_attempts=retries,
                     usage_by_model=by_model, infra_errors=sum(r["infra_errors"] for r in rows))
        result["cohorts"][cohort] = stats

    before, after = (result["cohorts"][name] for name in REVIEWERS)
    diffs = [(after["per_puzzle"][p]["solved"] - before["per_puzzle"][p]["solved"]) / REPEATS for p in expected]
    delta, low, high = bootstrap(diffs, random.Random(0))
    outcomes = [(before["per_puzzle"][p]["puzzle_solved"], after["per_puzzle"][p]["puzzle_solved"]) for p in expected]
    both = outcomes.count((True, True))
    before_only = outcomes.count((True, False))
    after_only = outcomes.count((False, True))
    neither = outcomes.count((False, False))
    d, lo, hi = newcombe_paired(both, before_only, after_only, neither)
    result["paired"] = {"unit": "puzzle (n=3)", "delta_exact_per_run": delta,
                        "cluster_ci95": [low, high], "delta_puzzles_solved": d,
                        "newcombe_ci95": [lo, hi], "exact_mcnemar_p": sign_test(before_only, after_only),
                        "before_only": before_only, "after_only": after_only,
                        "note": "Selected development puzzles and small n; no general performance claim. An all-zero bootstrap interval with identical outcomes does not establish equivalence."}
    (OUT / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")

    lines = ["# Public three-puzzle reviewer pilot", "", result["scope"], "",
             "GLM-5.3-Flash remains the default for all stages and the basis of the main evaluation. "
             "See [trial notes](README.md) for the protocol, limitations and interpretation.", "",
             "Each reviewer: three puzzles, one fresh run each. Fill, repair and crosscheck use GLM.", "",
             "| Metric | GLM review | Nemotron review |", "|---|---:|---:|"]
    metrics = [
        ("Exact solves", lambda s: f"{s['exact_count']}/{s['runs']} ({100*s['exact']['mean']:.1f}%)"),
        ("Clue accuracy", lambda s: f"{100*s['clue']['mean']:.2f}%"),
        ("Cell accuracy", lambda s: f"{100*s['cell']['mean']:.2f}%"),
        ("False accepts", lambda s: str(s['false_accept'])),
        ("Median review tokens", lambda s: f"{s['review_tokens_median']:,.0f}"),
        ("Median tokens", lambda s: f"{s['tokens_median']:,.0f}"),
        ("Median latency (s)", lambda s: f"{s['latency_median']:.1f}"),
        ("Total estimated USD", lambda s: f"${s['estimated_cost_usd_total']:.4f}"),
        ("Median estimated USD/run", lambda s: f"${s['estimated_cost_usd_median']:.4f}"),
    ]
    lines += [f"| {name} | {fmt(before)} | {fmt(after)} |" for name, fmt in metrics]
    lines += ["", "| Puzzle | GLM exact / 1 | Nemotron exact / 1 |", "|---|---:|---:|"]
    for p in PUZZLES:
        title = json.loads(p.read_text())["metadata"]["title"]
        lines.append(f"| {title} | {before['per_puzzle'][p.stem]['solved']} | {after['per_puzzle'][p.stem]['solved']} |")
    lines += ["", f"Paired exact-rate difference: {100*delta:+.1f} pp; 95% puzzle-cluster bootstrap CI [{100*low:+.1f}, {100*high:+.1f}] pp.",
              f"Exact per puzzle (one run): before-only {before_only}, after-only {after_only}; exact McNemar p={result['paired']['exact_mcnemar_p']:.4g}.",
              "The bootstrap interval is degenerate when all observed outcomes are identical; it does not establish equivalence or rule out rare failures.",
              "", result["cost_basis"] + " Only the six completed pilot runs are counted; the API smoke call is excluded.",
              "", f"Price sources: [Nebius GLM]({PRICE_SOURCES[0]}), [Nebius Nemotron]({PRICE_SOURCES[1]}).", ""]
    (OUT / "comparison.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
