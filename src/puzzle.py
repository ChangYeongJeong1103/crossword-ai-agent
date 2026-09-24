"""Crossword input and deterministic checks; no model or gold answers here."""
import json
import re
from collections import defaultdict
from pathlib import Path


def normalize(text, length):
    if not isinstance(text, str):
        return None
    answer = re.sub(r"[\s'’\-]", "", text).upper()
    return answer if re.fullmatch(r"[A-Z]+", answer) and len(answer) == length else None


class Puzzle:
    def __init__(self, data):
        self.id = data["puzzle_id"]
        self.grid = data["grid"]
        rows, cols = data["rows"], data["columns"]
        if rows < 1 or cols < 1 or len(self.grid) != rows or any(
            len(row) != cols or set(row) - {".", "#"} for row in self.grid
        ):
            raise ValueError("Expected a rectangular grid of '.' and '#' only.")
        self.title = data.get("metadata", {}).get("title", "")
        self.clues, self.cells = {}, defaultdict(list)
        for raw in data["clues"]:
            clue = {key: raw[key] for key in ("id", "text", "length", "direction", "start")}
            cid, n, direction = clue["id"], clue["length"], clue["direction"]
            if cid in self.clues or n < 1 or direction not in ("across", "down"):
                raise ValueError("Invalid or duplicate clue.")
            r, c = clue["start"]
            dr, dc = (0, 1) if direction == "across" else (1, 0)
            cells = [(r + dr * i, c + dc * i) for i in range(n)]
            if any(not (0 <= y < rows and 0 <= x < cols) or self.grid[y][x] == "#" for y, x in cells):
                raise ValueError(f"{cid}: slot outside the grid or through a block.")
            for y, x in ((r - dr, c - dc), (r + dr * n, c + dc * n)):
                if 0 <= y < rows and 0 <= x < cols and self.grid[y][x] != "#":
                    raise ValueError(f"{cid}: length/start does not match its full slot.")
            for i, cell in enumerate(cells):
                self.cells[cell].append((cid, i))
            self.clues[cid] = clue
        white = {(r, c) for r in range(rows) for c in range(cols) if self.grid[r][c] != "#"}
        if set(self.cells) != white or any(
            len(entries) > 2 or len({self.clues[k]["direction"] for k, _ in entries}) != len(entries)
            for entries in self.cells.values()
        ):
            raise ValueError("Every white cell must have valid, non-overlapping clue slots.")
        self.crossings = [tuple(entries) for entries in self.cells.values() if len(entries) == 2]

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def check(self, answers):
        valid = {cid: value for cid, raw in answers.items() if cid in self.clues
                 and (value := normalize(raw, self.clues[cid]["length"]))}
        conflicts = []
        for (a, i), (b, j) in self.crossings:
            if a in valid and b in valid and valid[a][i] != valid[b][j]:
                conflicts.append({"a": a, "a_index": i, "a_letter": valid[a][i],
                                  "b": b, "b_index": j, "b_letter": valid[b][j]})
        missing = sorted(set(self.clues) - set(valid))
        return valid, conflicts, missing

    def render(self, answers):
        valid, _, _ = self.check(answers)
        grid = [list(row) for row in self.grid]
        for (r, c), entries in self.cells.items():
            letters = {valid[cid][i] for cid, i in entries if cid in valid}
            grid[r][c] = next(iter(letters)) if len(letters) == 1 else "."
        return ["".join(row) for row in grid]

    def patterns(self, answers):
        valid, _, _ = self.check(answers)
        patterns = {cid: ["?"] * clue["length"] for cid, clue in self.clues.items()}
        for (a, i), (b, j) in self.crossings:
            if b in valid:
                patterns[a][i] = valid[b][j]
            if a in valid:
                patterns[b][j] = valid[a][i]
        return {cid: "".join(pattern) for cid, pattern in patterns.items()}
