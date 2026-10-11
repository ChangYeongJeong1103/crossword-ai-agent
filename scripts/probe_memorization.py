"""Memorization probe: can the model recall a puzzle's answers without its clues?

The model gets only the puzzle's identity (title, author, source, date) and each
slot's ID and length, and must guess every slot (abstaining would hide recall).
Common short fill is guessable by chance, so the signal is the gap between the
older Crossword Nexus puzzles and the post-release Crosshare set.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.llm_client import Client
from src.puzzle import Puzzle, normalize

ROOT = Path(__file__).parents[1]
SETS = {"crossword_nexus": ["data/benchmark/standard_15x15", "data/benchmark/held_out"],
        "crosshare": ["data/benchmark/crosshare_heldout"]}
SYSTEM = """You are asked to recall a specific published crossword from memory.
You get the puzzle's title, author, source and date, plus each answer slot's ID
and length, but not the clues. Return only JSON: {"answers": {"1A": "WORD"}}.
Give your best guess for every slot, even when unsure; never leave one empty."""


def probe(client, path, batch=20):
    puzzle = Puzzle.load(path)
    meta = json.loads(path.read_text())["metadata"]
    identity = {k: meta.get(k) for k in ("title", "author", "source", "published")}
    gold = json.loads((path.parents[1] / "gold" / path.name).read_text())["answers"]
    ids, answers, errors = list(puzzle.clues), {}, []
    for i in range(0, len(ids), batch):
        slots = [{"id": k, "length": puzzle.clues[k]["length"]} for k in ids[i:i + batch]]
        try:
            response = client.complete([{"role": "system", "content": SYSTEM},
                                        {"role": "user", "content": json.dumps({"puzzle": identity, "slots": slots})}])
            text = response["text"]
            values = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]["answers"]
            if not isinstance(values, dict):
                raise ValueError("answers must be an object")
        except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append(repr(error))
            continue
        for slot in slots:
            word = normalize(values.get(slot["id"], ""), slot["length"])
            if word:
                answers[slot["id"]] = word
    correct = sum(answers.get(k) == v for k, v in gold.items())
    return {"puzzle_id": puzzle.id, "published": meta.get("published"), "slots": len(gold),
            "attempted": len(answers), "correct": correct, "recall": correct / len(gold),
            "errors": errors, "answers": answers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "results/benchmark/probe")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    client = Client(max_calls=10000, token_budget=50_000_000)
    jobs = [(name, path) for name, folders in SETS.items() for folder in folders
            for path in sorted((ROOT / folder / "puzzles").glob("*.json"))]
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe, client, path): name for name, path in jobs}
        for future in as_completed(futures):  # Save each puzzle as soon as it finishes.
            result = {"set": futures[future], **future.result()}
            (args.out / f"{result['puzzle_id']}.json").write_text(json.dumps(result, indent=2) + "\n")
            results.append(result)
    for name in SETS:
        rows = [r for r in results if r["set"] == name]
        print(f"{name}: {len(rows)} puzzles, recall {sum(r['correct'] for r in rows)}/"
              f"{sum(r['slots'] for r in rows)}, errors {sum(len(r['errors']) for r in rows)}")


if __name__ == "__main__":
    main()
