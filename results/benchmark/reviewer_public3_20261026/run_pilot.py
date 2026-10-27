"""Three public puzzles, one fresh solve per reviewer, using the canonical runner."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import run_benchmark as benchmark
from src import config

OUT = Path(__file__).resolve().parent
PUZZLES = [ROOT / "data/benchmark/standard_15x15/puzzles" / f"crossword_nexus_{name}.json"
           for name in ("im_alright", "fm", "garden_party")]
# Keep the recorded cohorts independent of the application's current defaults.
REVIEWERS = {"glm_review": "zai-org/GLM-5.3-Flash", "nemotron_review": "nvidia/Nemotron-3.5-Super-VL"}
REPEATS = 1


def log(message):
    line = f"{datetime.now(timezone.utc).isoformat()} {message}"
    print(line, flush=True)
    with (OUT / "run.log").open("a") as stream:
        stream.write(line + "\n")


def main():
    source = benchmark.source_sha256()
    protocol = {
        "purpose": "Small diagnostic development pilot; not a generalization estimate.",
        "selection": "Three public CC BY 4.0 Crossword Nexus puzzles; no By George! or Gino.",
        "solver_model": config.MODEL, "reviewers": REVIEWERS, "runs_per_puzzle_per_reviewer": REPEATS,
        "workers": 1, "config_name": "L3_full",
        "settings": {name: benchmark.settings_for("L3_full", reviewer)[1] for name, reviewer in REVIEWERS.items()},
        "source_sha256": source, "runner_sha256": benchmark.runner_sha256(),
        "puzzles": [{"path": str(p.relative_to(ROOT)), "puzzle_id": p.stem,
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in PUZZLES],
        "comparison": "Review model plus required reviewer confirmation of solver-side repair changes.",
        "transport": "Shared bounded retries now include observed HTTP 529; one puzzle at a time.",
        "statistics": "Descriptive paired puzzle outcomes (n=3); no reliability or equivalence claim.",
        "infra_policy": "Stop before the next run if any request remains failed after HTTP retries.",
    }
    manifest = OUT / "protocol.json"
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        if any(saved.get(k) != v for k, v in protocol.items()):
            raise SystemExit("Pilot protocol changed; use a new output folder.")
    else:
        manifest.write_text(json.dumps({**protocol, "created_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n")

    # Attach a progress observer only; inference remains in the canonical solve/run_one functions.
    original_solve = benchmark.solve

    def observed_solve(*args, **kwargs):
        kwargs["progress"] = lambda r: log(
            f"round={r['round']} phase={r['phase']} answered={r['answered']} "
            f"calls={r['calls']} errors={r['error'] or 'none'}")
        return original_solve(*args, **kwargs)

    benchmark.solve = observed_solve
    for index, puzzle in enumerate(PUZZLES):
        # Alternate the first reviewer across puzzles to reduce a fixed order effect.
        cohorts = list(REVIEWERS.items())[::1 if index % 2 == 0 else -1]
        for cohort, reviewer in cohorts:
            out = OUT / cohort / "runs" / "L3_full" / puzzle.stem / "run1.json"
            if out.exists():
                problems = benchmark.mismatch(out, "L3_full", puzzle, config.MODEL, source, 1, reviewer)
                if problems:
                    raise SystemExit(f"Incompatible result: {out}: {problems}")
                result = json.loads(out.read_text())
            else:
                if benchmark.source_sha256() != source:
                    raise SystemExit("Source changed during the pilot.")
                log(f"START {cohort} {puzzle.stem}")
                result = benchmark.run_one("L3_full", puzzle, 1, out, config.MODEL, source, reviewer)
                log(f"DONE {cohort} {puzzle.stem} exact={result['evaluation']['exact_solve']} "
                    f"tokens={result['tokens']} seconds={result['latency_seconds']:.1f}")
            errors = benchmark.infra_errors(result)
            if errors:
                raise SystemExit(f"Stopped: {errors} residual infrastructure errors; saved for diagnosis, not a clean comparison.")


if __name__ == "__main__":
    main()
