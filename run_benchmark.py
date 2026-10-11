"""Run every {config x puzzle x run} solve and save one JSON per run.

A finished run is skipped only if it was produced by the same source, model,
config and puzzle file; any mismatch stops the benchmark instead of mixing runs.
Gold is opened only after solve() returns, exactly as in run_eval.py.

With --rerun-infra-errors, a saved run that contains a request which still failed
after the client's HTTP retries is archived and run again, regardless of its
outcome, for at most three attempts in total. The kept attempt is the first one
without such errors, or the last one; a ledger records every archived attempt.
"""
import argparse
import hashlib
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.evaluator import evaluate
from src.llm_client import Client, load_env
from src.puzzle import Puzzle
from src.solver import solve

ROOT = Path(__file__).parent
MAX_ATTEMPTS = 3  # The first attempt plus at most two reruns for infrastructure errors.
# Ablation ladder (L0-L3), the full controller without crosscheck, and batch-size
# variants of the full controller. Crosscheck needs review, so L0-L2 record it as
# off. Every config shares the 400k-token budget. Single-clue batches need about
# four times as many requests for the same work, so their HTTP-attempt cap is
# scaled to keep the token budget, not the request count, as the binding limit.
CONFIGS = {
    "L0_single_pass": {"max_rounds": 1, "repair": False, "review": False, "crosscheck": False},
    "L1_fill_loop": {"repair": False, "review": False, "crosscheck": False},
    "L2_fill_repair": {"review": False, "crosscheck": False},
    "L3_full": {},
    "L3_no_crosscheck": {"crosscheck": False},
    "L3_batch1": {"batch_size": 1, "max_calls": 4 * config.MAX_CALLS},
    "L3_batch_all": {"batch_size": None},
}


def source_sha256():
    files = sorted((ROOT / "src").rglob("*.py"))
    return hashlib.sha256(b"".join(path.read_bytes() for path in files)).hexdigest()


def runner_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def settings_for(name):
    """Solver keyword arguments and the full recorded config for one configuration."""
    settings = {"max_rounds": config.MAX_ROUNDS, "batch_size": config.BATCH_SIZE,
                "repair": True, "review": True, "crosscheck": True, **CONFIGS[name]}
    max_calls = settings.pop("max_calls", config.MAX_CALLS)
    return settings, {**settings, "max_tokens": config.MAX_TOKENS, "max_calls": max_calls,
                      "token_budget": config.TOKEN_BUDGET}


def mismatch(out, name, puzzle_path, model, source, run=None):
    """Why a saved run is not comparable with the current setup, or None."""
    try:
        saved = json.loads(out.read_text())
    except (OSError, ValueError):
        return ["unreadable result"]
    if not isinstance(saved, dict):
        return ["invalid result object"]
    expected = {"source_sha256": source, "model": model, "config": settings_for(name)[1],
                "puzzle_sha256": hashlib.sha256(puzzle_path.read_bytes()).hexdigest()}
    problems = [key for key, value in expected.items() if saved.get(key) != value]
    if saved.get("config_name") != name:
        problems.append("config_name")
    if saved.get("puzzle_id") != json.loads(puzzle_path.read_text())["puzzle_id"]:
        problems.append("puzzle_id")
    if type(saved.get("run")) is not int or saved["run"] < 1 or (run is not None and saved["run"] != run):
        problems.append("run")
    for key, kind in (("answers", dict), ("evaluation", dict), ("trace", list)):
        if not isinstance(saved.get(key), kind):
            problems.append(key)
    if isinstance(saved.get("evaluation"), dict) and type(saved["evaluation"].get("exact_solve")) is not bool:
        problems.append("evaluation.exact_solve")
    for key in ("termination", "calls", "tokens", "latency_seconds"):
        if key not in saved:
            problems.append(key)
    return problems or None


def infra_errors(result):
    """Requests that still failed after the client's HTTP retries (not model output)."""
    return sum((x.get("error") or "").startswith("Token Factory")
               for t in result.get("trace", []) for x in t.get("responses", []))


def rerun_infra_errors(jobs, output, archive):
    """Archive saved runs with infrastructure errors so they run again; return how many moved."""
    ledger_path = archive / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    archived = Counter((e["config"], e["puzzle_id"], e["run"]) for e in ledger)
    moved = 0
    for name, path, run in jobs:
        out = output(name, path, run)
        if not out.exists():
            continue
        saved = json.loads(out.read_text())
        errors, attempt = infra_errors(saved), archived[(name, path.stem, run)] + 1
        if not errors or attempt >= MAX_ATTEMPTS:  # Clean, or the last allowed attempt: keep it.
            continue
        destination = archive / name / path.stem / f"run{run}_attempt{attempt}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        out.replace(destination)
        ledger.append({"config": name, "puzzle_id": path.stem, "run": run, "attempt": attempt,
                       "infra_errors": errors, "tokens": saved.get("tokens", 0),
                       "archived": str(destination.relative_to(archive)),
                       "archived_at": datetime.now(timezone.utc).isoformat()})
        moved += 1
    archive.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
    return moved


def run_one(name, puzzle_path, run, out, model, source):
    settings, recorded = settings_for(name)
    puzzle = Puzzle.load(puzzle_path)
    result = solve(puzzle, Client(model, max_calls=recorded["max_calls"]), **settings)
    result["evaluation"] = evaluate(puzzle, result["answers"], puzzle_path.parents[1] / "gold" / puzzle_path.name)
    result.update(config_name=name, run=run, created_at=datetime.now(timezone.utc).isoformat(),
                  source_sha256=source, runner_sha256=runner_sha256(), config=recorded,
                  puzzle_sha256=hashlib.sha256(puzzle_path.read_bytes()).hexdigest())
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".tmp")
    partial.write_text(json.dumps(result, indent=2) + "\n")
    partial.rename(out)  # A crash never leaves a half-written run behind.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, nargs="+",
                        default=[ROOT / "data/benchmark/crosshare_heldout/puzzles"],
                        help="one or more folders of puzzle JSON files")
    parser.add_argument("--configs", nargs="+", default=list(CONFIGS), choices=list(CONFIGS))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--workers", type=int, default=6, help="puzzles solved concurrently")
    parser.add_argument("--limit", type=int, help="only the first N puzzles (quick checks)")
    parser.add_argument("--model")
    parser.add_argument("--out", type=Path, default=ROOT / "results/benchmark/runs")
    parser.add_argument("--rerun-infra-errors", action="store_true",
                        help="archive saved runs with infrastructure errors and run them again")
    args = parser.parse_args()
    if min(args.runs, args.workers) < 1 or (args.limit is not None and args.limit < 1):
        parser.error("runs, workers and limit must be positive")

    load_env(ROOT / ".env")
    model = args.model or os.environ.get("NEBIUS_MODEL", config.MODEL)
    source = source_sha256()
    puzzles = sorted((p for folder in args.puzzles for p in folder.glob("*.json")),
                     key=lambda p: p.name)[:args.limit]
    if not puzzles or len({p.stem for p in puzzles}) != len(puzzles):
        parser.error("provide at least one puzzle and no duplicate puzzle filenames")
    if len(set(args.configs)) != len(args.configs):
        parser.error("configurations must be unique")
    # Run index first: after each pass every config has a paired run on every puzzle.
    jobs = [(name, path, run) for run in range(1, args.runs + 1) for path in puzzles
            for name in args.configs]
    output = lambda name, path, run: args.out / name / path.stem / f"run{run}.json"
    if args.rerun_infra_errors:
        moved = rerun_infra_errors(jobs, output, args.out.parent / f"{args.out.name}_reruns")
        print(f"archived {moved} runs with infrastructure errors for another attempt", flush=True)
    done_jobs = [job for job in jobs if output(*job).exists()]
    conflicts = {output(*job): why for job in done_jobs
                 if (why := mismatch(output(*job), job[0], job[1], model, source, job[2]))}
    if conflicts:
        for path, why in conflicts.items():
            print(f"incompatible saved run {path}: {', '.join(why)} differ", flush=True)
        raise SystemExit("Saved runs differ from the current setup; use a new --out folder.")
    todo = [job for job in jobs if job not in done_jobs]
    print(f"{len(done_jobs)} of {len(jobs)} runs already done; {len(todo)} to go "
          f"(source {source[:12]}, model {model})", flush=True)
    started, done, failed = time.monotonic(), 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, name, path, run, output(name, path, run), model, source):
                   (name, path.stem, run) for name, path, run in todo}
        for future in as_completed(futures):
            name, puzzle_id, run = futures[future]
            done += 1
            try:
                result = future.result()
            except Exception as error:  # Leave the run missing so a rerun retries it.
                failed += 1
                print(f"[{done}/{len(todo)}] {name} {puzzle_id} run{run}: FAILED {error!r}", flush=True)
                continue
            e = result["evaluation"]
            print(f"[{done}/{len(todo)}] {name} {puzzle_id} run{run}: exact={e['exact_solve']} "
                  f"clue={e['clue_accuracy']:.3f} tokens={result['tokens']} "
                  f"{result['termination']} {result['latency_seconds']:.0f}s "
                  f"(elapsed {(time.monotonic() - started) / 60:.0f}m)", flush=True)
    if failed:  # Completed runs are kept; rerunning the same command retries only the failed ones.
        raise SystemExit(f"{failed} of {len(todo)} runs failed; rerun the same command to retry them.")


if __name__ == "__main__":
    main()
