"""Gold is used only here, after inference; blanks count as incorrect."""
import json
from pathlib import Path


def evaluate(puzzle, answers, gold_path):
    payload = json.loads(Path(gold_path).read_text())
    if payload.get("puzzle_id") != puzzle.id:
        raise ValueError("Gold belongs to a different puzzle.")
    gold, conflicts, missing = puzzle.check(payload["answers"])
    if conflicts or missing or set(payload["answers"]) != set(puzzle.clues):
        raise ValueError("Gold must contain a complete, valid, consistent solution.")
    valid, conflicts, missing = puzzle.check(answers)
    predicted, expected = puzzle.render(valid), puzzle.render(gold)
    clue_correct = sum(valid.get(cid) == word for cid, word in gold.items())
    cell_correct = sum(predicted[r][c] == expected[r][c] for r, c in puzzle.cells)
    return {"exact_solve": clue_correct == len(gold) and not conflicts,
            "clue_correct": clue_correct, "clue_total": len(gold),
            "clue_accuracy": clue_correct / len(gold),
            "cell_correct": cell_correct, "cell_total": len(puzzle.cells),
            "cell_accuracy": cell_correct / len(puzzle.cells),
            "coverage": len(valid) / len(gold), "conflicts": len(conflicts)}
