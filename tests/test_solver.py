"""Deterministic controller checks; these do not measure model quality."""
import json
from pathlib import Path

import pytest

from src.evaluator import evaluate
from src.puzzle import Puzzle, normalize
from src.solver import prune, solve

DATA = Path(__file__).parents[1] / "data/synthetic"


class FakeClient:
    """Return deterministic clue answers without a model call."""

    model = "test-double"

    def __init__(self, answer):
        self.answer, self.messages = answer, []

    def complete(self, messages, max_tokens=None):
        self.messages.append(messages)
        context = json.loads(messages[1]["content"])
        replies = {
            clue["id"]: self.answer({"pattern": "review", **clue})
            for clue in context["clues"]
        }
        return {
            "text": json.dumps({"answers": replies}),
            "usage": {"total_tokens": 5},
            "latency_seconds": 0,
            "finish_reason": "stop",
        }


def fixture():
    """Load the shared synthetic crossword and gold answers."""
    puzzle = Puzzle.load(DATA / "puzzles/mini_001.json")
    path = DATA / "gold/mini_001.json"
    return puzzle, path, json.loads(path.read_text())["answers"]


def test_recovery_with_crossing_feedback():
    puzzle, path, gold = fixture()
    client = FakeClient(
        lambda clue: "CRONY"
        if clue["id"] == "1A" and clue["pattern"] == "?????"
        else gold[clue["id"]]
    )
    result = solve(puzzle, client)
    assert result["trace"][0]["removed"] == {"1A": "CRONY"}
    assert result["trace"][1]["changes"]["1A"]["after"] == gold["1A"]
    assert evaluate(puzzle, result["answers"], path)["exact_solve"]


def test_wrong_length_is_rejected_not_truncated():
    puzzle, _, _ = fixture()
    result = solve(puzzle, FakeClient(lambda clue: "SWAMPS"), max_rounds=1)
    assert not result["answers"]
    assert len(result["trace"][0]["rejected"]) == len(puzzle.clues)
    assert normalize("New York", 7) == "NEWYORK"
    assert normalize("Café", 4) is None


def test_mask_disagreement_is_rejected():
    puzzle, _, gold = fixture()

    def response(clue):
        if clue["id"] in {"1A", "1D"}:
            return gold[clue["id"]]
        return "" if clue["pattern"] == "?????" else "ZZZZZ"

    result = solve(puzzle, FakeClient(response), max_rounds=2)
    assert result["trace"][1]["rejected"]
    assert all("Z" not in answer for answer in result["answers"].values())
    assert not puzzle.check(result["answers"])[1]


def test_consistent_regions_are_not_discarded():
    puzzle, _, gold = fixture()
    separate = {k: value for k, value in gold.items() if k.endswith("A")}
    assert prune(puzzle, separate) == separate


def test_stall_is_bounded_and_no_gold_is_sent():
    puzzle, _, _ = fixture()
    client = FakeClient(lambda clue: "")
    result = solve(puzzle, client)
    assert result["termination"] == "stalled"
    assert result["calls"] <= 3
    context = json.loads(client.messages[0][1]["content"])
    assert "gold" not in context
    assert all("answer" not in clue for clue in context["clues"])


def test_consistent_wrong_grid_is_not_exact():
    puzzle, path, _ = fixture()
    result = solve(
        puzzle, FakeClient(lambda clue: "X" * clue["length"])
    )
    assert result["termination"] == "complete_consistent_grid"
    assert not evaluate(puzzle, result["answers"], path)["exact_solve"]


@pytest.mark.parametrize(
    "name",
    [
        "by_george",
        "garden_party",
        "gino_the_manager",
        "im_alright",
        "what_a_fool_believes",
    ],
)
def test_standard_fixtures(name):
    root = DATA.parent / "benchmark/standard_15x15"
    filename = f"crossword_nexus_{name}.json"
    puzzle = Puzzle.load(root / "puzzles" / filename)
    assert len(puzzle.grid) == 15
    assert all(len(row) == 15 for row in puzzle.grid)
    assert all(len(entries) == 2 for entries in puzzle.cells.values())
    gold_path = root / "gold" / filename
    gold = json.loads(gold_path.read_text())["answers"]
    assert evaluate(puzzle, gold, gold_path)["exact_solve"]


def test_review_correction_repairs_neighbor():
    puzzle, path, gold = fixture()
    bad = {
        **gold,
        "1A": "X" + gold["1A"][1:],
        "1D": "X" + gold["1D"][1:],
    }

    class Reviewer(FakeClient):
        def complete(self, messages, max_tokens=None):
            self.messages.append(messages)
            context = json.loads(messages[1]["content"])
            if context["mode"] == "fill":
                source = bad
            elif context["mode"] == "review":
                source = {**gold, "1D": bad["1D"]}
            else:
                source = gold
            answers = {
                clue["id"]: source[clue["id"]]
                for clue in context["clues"]
            }
            return {"text": json.dumps({"answers": answers}), "usage": {}}

    client = Reviewer(None)
    result = solve(puzzle, client)
    assert evaluate(puzzle, result["answers"], path)["exact_solve"]
    assert any(
        json.loads(messages[1]["content"])["mode"] == "repair"
        for messages in client.messages
    )


def test_empty_review_cannot_mark_grid_as_reviewed():
    puzzle, _, gold = fixture()

    class EmptyReview(FakeClient):
        def complete(self, messages, max_tokens=None):
            context = json.loads(messages[1]["content"])
            if context["mode"] != "fill":
                return {
                    "text": "",
                    "finish_reason": "length",
                    "usage": {"total_tokens": 5},
                }
            return super().complete(messages, max_tokens)

    result = solve(
        puzzle,
        EmptyReview(lambda clue: gold[clue["id"]]),
        max_rounds=2,
    )
    assert result["termination"] == "round_limit"
    assert result["trace"][-1]["reviewed"] == 0
    assert result["tokens"] > 0


def test_empty_batch_splits_and_preserves_usage():
    puzzle, path, gold = fixture()
    attempts = []

    class SplitClient(FakeClient):
        def complete(self, messages, max_tokens=None):
            context = json.loads(messages[1]["content"])
            attempts.append((len(context["clues"]), max_tokens))
            if len(context["clues"]) > 1:
                return {
                    "text": "",
                    "finish_reason": "length",
                    "usage": {"total_tokens": 10},
                }
            return super().complete(messages, max_tokens)

    result = solve(puzzle, SplitClient(lambda clue: gold[clue["id"]]))
    expected_tokens = sum(
        response["usage"]["total_tokens"]
        for record in result["trace"]
        for response in record["responses"]
    )
    assert evaluate(puzzle, result["answers"], path)["exact_solve"]
    assert result["tokens"] == expected_tokens
    assert any(size == 1 for size, _ in attempts)
    assert not any(
        size == 1 and max_tokens == 12000
        for size, max_tokens in attempts
    )


def test_empty_split_singleton_has_no_larger_retry():
    puzzle, _, _ = fixture()
    attempts = []

    class EmptySplitClient(FakeClient):
        def complete(self, messages, max_tokens=None):
            context = json.loads(messages[1]["content"])
            attempts.append((len(context["clues"]), max_tokens))
            return {
                "text": "",
                "finish_reason": "length",
                "usage": {"total_tokens": 10},
            }

    solve(puzzle, EmptySplitClient(None), max_rounds=1)
    assert any(size == 1 for size, _ in attempts)
    assert not any(
        size == 1 and max_tokens == 12000
        for size, max_tokens in attempts
    )


def test_fully_crossed_word_still_requires_confirmation():
    puzzle, _, gold = fixture()
    client = FakeClient(
        lambda clue: "" if clue["id"] == "1A" else gold[clue["id"]]
    )
    result = solve(puzzle, client, max_rounds=2)
    assert "1A" not in result["answers"]


def test_http_retry_and_hard_call_limit(monkeypatch):
    import io
    from urllib.error import HTTPError

    from src.llm_client import BudgetExceeded, Client

    monkeypatch.setenv("NEBIUS_API_KEY", "unit-test-placeholder")
    attempts = []

    def response(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise HTTPError(
                "test", 429, "rate limited", {"Retry-After": "0"}, None
            )
        payload = {
            "choices": [{
                "message": {"content": "{}"},
                "finish_reason": "stop",
            }],
            "usage": {"total_tokens": 7},
        }
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr("src.llm_client.urllib.request.urlopen", response)
    monkeypatch.setattr("src.llm_client.time.sleep", lambda _: None)
    client = Client(max_calls=2)
    output = client.complete([])
    assert client.calls == 2
    assert client.tokens == 7
    assert output["http_attempts"] == 2
    with pytest.raises(BudgetExceeded):
        client.complete([])


def test_cross_referenced_clue_without_shared_cell():
    puzzle, path, gold = fixture()
    puzzle.clues["1A"]["text"] = "See 2-Down"

    class NeedsReference(FakeClient):
        def complete(self, messages, max_tokens=None):
            context = json.loads(messages[1]["content"])
            refs = {
                clue["id"]: clue
                for clue in context["referenced_clues"]
            }
            answers = {
                clue["id"]: gold[clue["id"]]
                for clue in context["clues"]
            }
            expected = puzzle.clues["2D"]["text"]
            if "1A" in answers and refs.get("2D", {}).get("clue") != expected:
                answers["1A"] = ""
            return {"text": json.dumps({"answers": answers}), "usage": {}}

    result = solve(puzzle, NeedsReference(None))
    assert evaluate(puzzle, result["answers"], path)["exact_solve"]


def test_local_repair_keeps_completed_grid_review():
    puzzle, _, gold = fixture()

    class NeedsRepair(FakeClient):
        def complete(self, messages, max_tokens=None):
            self.messages.append(messages)
            context = json.loads(messages[1]["content"])
            answers = {
                clue["id"]: ""
                if clue["id"] == "1A" and context["mode"] == "fill"
                else gold[clue["id"]]
                for clue in context["clues"]
            }
            return {"text": json.dumps({"answers": answers}), "usage": {}}

    client = NeedsRepair(None)
    result = solve(puzzle, client)
    assert result["termination"] == "complete_consistent_grid"
    reviewed = {
        clue["id"]
        for messages in client.messages
        for context in [json.loads(messages[1]["content"])]
        if context["mode"] == "review"
        for clue in context["clues"]
    }
    assert reviewed == set(puzzle.clues)


def test_unaccepted_full_pattern_triggers_repair():
    puzzle, path, gold = fixture()
    later = next(
        k for k in puzzle.clues if k.endswith("A") and k != "1A"
    )

    class LocalRepair(FakeClient):
        def complete(self, messages, max_tokens=None):
            context = json.loads(messages[1]["content"])
            answers = {}
            for clue in context["clues"]:
                blocked = (
                    context["mode"] == "fill"
                    and (
                        clue["id"] == "1A"
                        or (
                            clue["id"] == later
                            and clue["pattern"] == "?" * clue["length"]
                        )
                    )
                )
                answers[clue["id"]] = (
                    "" if blocked else gold[clue["id"]]
                )
            return {"text": json.dumps({"answers": answers}), "usage": {}}

    result = solve(puzzle, LocalRepair(None))
    assert result["trace"][1]["answered"] > result["trace"][0]["answered"]
    assert result["trace"][2]["phase"] == "repair"
    assert evaluate(puzzle, result["answers"], path)["exact_solve"]


def test_resolved_conflicting_pair_is_not_queried_again():
    puzzle, path, gold = fixture()
    repairs = []

    class Reviewer(FakeClient):
        def complete(self, messages, max_tokens=None):
            context = json.loads(messages[1]["content"])
            answers = {
                clue["id"]: gold[clue["id"]]
                for clue in context["clues"]
            }
            if context["mode"] == "review" and "1A" in answers:
                changed = "".join(
                    "X" if char != "X" else "Y"
                    for char in gold["1A"][:2]
                )
                answers["1A"] = changed + gold["1A"][2:]
            if context["mode"] == "repair":
                repairs.append(context)
            return {"text": json.dumps({"answers": answers}), "usage": {}}

    result = solve(puzzle, Reviewer(None))
    assert len(repairs) == 1
    assert evaluate(puzzle, result["answers"], path)["exact_solve"]
