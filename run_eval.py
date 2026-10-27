"""Solve first; optionally load gold and score afterwards."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.evaluator import evaluate
from src.llm_client import Client
from src.puzzle import Puzzle
from src.solver import solve


def main():
    """Run one puzzle and save its complete result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzle", required=True, type=Path)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--review-model", help="semantic reviewer (default: NEBIUS_REVIEW_MODEL or GLM-5.3-Flash)")
    parser.add_argument("--max-rounds", type=int, default=config.MAX_ROUNDS)
    parser.add_argument("--max-tokens", type=int, default=config.MAX_TOKENS)
    parser.add_argument("--max-calls", type=int, default=config.MAX_CALLS)
    parser.add_argument("--token-budget", type=int, default=config.TOKEN_BUDGET)
    parser.add_argument(
        "--output", type=Path, default=Path("live_runs/latest.json")
    )
    args = parser.parse_args()

    puzzle = Puzzle.load(args.puzzle)
    rounds = []

    def progress(record):
        rounds.append(record)
        checkpoint = {
            "puzzle_id": puzzle.id,
            "status": "running",
            "trace": rounds,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(checkpoint, indent=2))
        print(
            f"{puzzle.id} · Round {record['round']}: "
            f"{record['answered']} answers, "
            f"{record['conflicts']} conflicts, "
            f"{record['latency_seconds']:.1f}s",
            flush=True,
        )
        if record["error"]:
            print(record["error"], flush=True)

    client = Client(
        args.model, args.max_tokens, args.max_calls, args.token_budget, review_model=args.review_model
    )
    result = solve(puzzle, client, args.max_rounds, progress)
    result["created_at"] = datetime.now(timezone.utc).isoformat()
    result["config"] = {
        "max_rounds": args.max_rounds,
        "batch_size": config.BATCH_SIZE,
        "repair": True,
        "review": True,
        "review_model": client.review_model,
        "crosscheck": True,
        "max_tokens": args.max_tokens,
        "max_calls": args.max_calls,
        "token_budget": args.token_budget,
    }
    source_files = sorted(
        (Path(__file__).parent / "src").rglob("*.py")
    )
    result["source_sha256"] = hashlib.sha256(
        b"".join(path.read_bytes() for path in source_files)
    ).hexdigest()

    if args.gold:
        result["evaluation"] = evaluate(
            puzzle, result["answers"], args.gold
        )
        print(json.dumps(result["evaluation"], indent=2))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['termination']}; saved {args.output}")


if __name__ == "__main__":
    main()
