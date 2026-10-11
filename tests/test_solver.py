"""Deterministic controller checks; these do not measure model quality."""
import json
from collections import Counter
from pathlib import Path

import pytest

from src.evaluator import evaluate
from src.llm_client import BudgetExceeded
from src.puzzle import Puzzle, normalize
from src.solver import prune, solve, suspect_pairs

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
        "fm",
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


def test_conflicts_are_counted_before_pruning():
    puzzle, _, gold = fixture()
    client = FakeClient(
        lambda clue: "CRONY"
        if clue["id"] == "1A" and clue["pattern"] == "?????"
        else gold[clue["id"]]
    )
    result = solve(puzzle, client)
    assert result["trace"][0]["conflicts"] > 0
    assert not puzzle.check(result["answers"])[1]


@pytest.mark.parametrize("batch_size, requests", [(1, 10), (4, 3), (None, 1)])
def test_batch_size_controls_requests_per_round(batch_size, requests):
    puzzle, path, gold = fixture()
    client = FakeClient(lambda clue: gold[clue["id"]])
    result = solve(puzzle, client, batch_size=batch_size)
    first = [json.loads(m[1]["content"]) for m in client.messages[:requests]]
    assert all(context["mode"] == "fill" for context in first)
    assert sum(len(context["clues"]) for context in first) == len(puzzle.clues)
    assert evaluate(puzzle, result["answers"], path)["exact_solve"]


def test_without_review_a_complete_grid_is_accepted():
    puzzle, _, gold = fixture()
    client = FakeClient(lambda clue: gold[clue["id"]])
    result = solve(puzzle, client, review=False)
    assert result["termination"] == "complete_consistent_grid"
    assert len(result["trace"]) == 1
    assert all(
        json.loads(m[1]["content"])["mode"] == "fill" for m in client.messages
    )


def test_without_repair_a_stalled_fill_stops():
    puzzle, _, gold = fixture()
    client = FakeClient(
        lambda clue: "" if clue["id"] == "1A" else gold[clue["id"]]
    )
    result = solve(puzzle, client, repair=False, review=False)
    assert result["termination"] == "stalled"
    assert "1A" not in result["answers"]
    assert all(
        json.loads(m[1]["content"])["mode"] == "fill" for m in client.messages
    )


def test_without_repair_fill_continues_while_progressing():
    puzzle, _, gold = fixture()
    asked = Counter()

    def answer(clue):
        asked[clue["id"]] += 1
        if clue["id"] == "1A" or (clue["id"] == "6A" and asked["6A"] < 2) or (
                clue["id"] == "7A" and asked["7A"] < 3):
            return ""
        return gold[clue["id"]]

    result = solve(puzzle, FakeClient(answer), repair=False, review=False)
    assert result["termination"] == "stalled"
    assert "7A" in result["answers"] and "1A" not in result["answers"]
    assert all(record["phase"] == "fill" for record in result["trace"])


def consistent_wrong_pair(gold):
    """Gold grid with 1A and 1D sharing one wrong cell, so crossings still agree."""
    return {**gold, "1A": "X" + gold["1A"][1:], "1D": "X" + gold["1D"][1:]}


def test_suspect_pairs_flag_near_miss_crossings():
    puzzle, _, gold = fixture()
    bad = consistent_wrong_pair(gold)
    assert suspect_pairs(puzzle, bad, gold) == {("1A", "1D"): {"1A": gold["1A"], "1D": gold["1D"]}}
    # A crossing-free answer far from the grid answer is a different reading, not a suspect.
    assert suspect_pairs(puzzle, gold, {"1A": "ZZZZZ"}) == {}


class Anchored(FakeClient):
    """Fills a consistent wrong pair and approves it in review, like an anchored model."""

    def __init__(self, gold):
        super().__init__(None)
        self.gold, self.bad, self.reviewed = gold, consistent_wrong_pair(gold), False

    def complete(self, messages, max_tokens=None):
        self.messages.append(messages)
        context = json.loads(messages[1]["content"])
        mode = context["mode"]
        self.reviewed |= mode == "review"
        answers = {}
        for clue in context["clues"]:
            k = clue["id"]
            if mode == "fill":  # Before review: anchored fill; afterwards: crossing-free attempt.
                answers[k] = self.gold[k] if self.reviewed else self.bad[k]
            elif mode == "review":
                answers[k] = clue["answer"]
            else:  # Repair with an alternative picks the alternative.
                answers[k] = clue.get("alternative", clue["answer"])
        return {"text": json.dumps({"answers": answers}), "usage": {}}


def test_crosscheck_repairs_consistent_wrong_pair():
    puzzle, path, gold = fixture()
    client = Anchored(gold)
    result = solve(puzzle, client)
    assert evaluate(puzzle, result["answers"], path)["exact_solve"]
    check = next(r for r in result["trace"] if r["phase"] == "crosscheck")
    assert check["suspects"] == [["1A", "1D"]]
    assert result["termination"] == "complete_consistent_grid"
    assert result["crosscheck_status"] == "completed"
    assert sum(r["phase"] == "crosscheck" for r in result["trace"]) == 1


def test_without_crosscheck_the_wrong_pair_survives():
    puzzle, path, gold = fixture()
    result = solve(puzzle, Anchored(gold), crosscheck=False)
    assert result["termination"] == "complete_consistent_grid"
    assert not evaluate(puzzle, result["answers"], path)["exact_solve"]
    assert all(r["phase"] != "crosscheck" for r in result["trace"])


def test_crosscheck_is_skipped_when_no_round_remains():
    puzzle, _, gold = fixture()
    no_review = solve(puzzle, FakeClient(lambda clue: gold[clue["id"]]), review=False)
    assert all(r["phase"] != "crosscheck" for r in no_review["trace"])
    assert no_review["crosscheck_status"] == "disabled"
    last = solve(puzzle, FakeClient(lambda clue: gold[clue["id"]]), max_rounds=2)
    assert last["termination"] == "round_limit"
    assert last["crosscheck_status"] == last["trace"][-1]["crosscheck_status"] == "skipped"
    assert last["answers"] == gold and last["submitted_verified"]


def test_crosscheck_is_not_reached_without_a_verified_grid():
    puzzle, _, _ = fixture()
    result = solve(puzzle, FakeClient(lambda clue: ""))
    assert result["crosscheck_status"] == "not_reached"
    assert not result["submitted_verified"] and result["answers"] == {}


class AfterReview(FakeClient):
    """Answers gold, then misbehaves in the crosscheck pass (fill requests after review)."""

    def __init__(self, gold, failure):
        super().__init__(lambda clue: gold[clue["id"]])
        self.gold, self.failure, self.reviewed = gold, failure, False

    def complete(self, messages, max_tokens=None):
        context = json.loads(messages[1]["content"])
        self.reviewed |= context["mode"] == "review"
        if self.reviewed and context["mode"] == "fill":
            if self.failure == "transport":
                raise RuntimeError("model unavailable")
            if self.failure == "budget":
                raise BudgetExceeded("test budget exhausted")
            values = {c["id"]: "" if self.failure == "abstain" else self.gold[c["id"]]
                      for c in context["clues"] if self.failure != "partial" or c["id"] != "1A"}
            return {"text": json.dumps({"answers": values}), "usage": {}}
        return super().complete(messages, max_tokens)


@pytest.mark.parametrize("failure, status", [("abstain", "completed"), ("partial", "incomplete"),
                                             ("transport", "incomplete"), ("budget", "incomplete")])
def test_crosscheck_blanks_are_answers_but_failed_requests_are_not(failure, status):
    puzzle, path, gold = fixture()
    result = solve(puzzle, AfterReview(gold, failure))
    # The verified grid stands either way; only the check's own status differs.
    assert result["crosscheck_status"] == status
    assert result["termination"] == "complete_consistent_grid"
    assert result["answers"] == gold and result["submitted_verified"]
    assert result["trace"][-1]["phase"] == "crosscheck"


def test_crosscheck_joint_repair_failure_leaves_the_verified_grid():
    puzzle, _, gold = fixture()

    class FailedRepair(Anchored):
        def complete(self, messages, max_tokens=None):
            if json.loads(messages[1]["content"])["mode"] == "repair":
                raise RuntimeError("repair unavailable")
            return super().complete(messages, max_tokens)

    client = FailedRepair(gold)
    result = solve(puzzle, client)
    assert result["crosscheck_status"] == "incomplete"
    assert result["termination"] == "complete_consistent_grid"
    assert result["trace"][-1]["suspects"] == [["1A", "1D"]]
    assert result["answers"] == client.bad


def test_budget_end_after_a_crosscheck_change_submits_the_last_verified_grid():
    puzzle, _, gold = fixture()

    class BudgetAfterCheck(Anchored):
        repaired = False

        def complete(self, messages, max_tokens=None):
            mode = json.loads(messages[1]["content"])["mode"]
            if mode == "review" and self.repaired:
                raise BudgetExceeded("test budget exhausted")
            self.repaired |= mode == "repair"
            return super().complete(messages, max_tokens)

    client = BudgetAfterCheck(gold)
    result = solve(puzzle, client)
    check = next(r for r in result["trace"] if r["phase"] == "crosscheck")
    assert set(check["changes"]) == {"1A", "1D"}  # The check found the fix ...
    assert result["termination"] == "budget_limit"  # ... but could not verify it in budget.
    assert result["answers"] == client.bad and result["submitted_verified"]


@pytest.mark.parametrize("batch_size", [1, 4, None])
def test_crosscheck_pass_uses_the_default_batch_size(batch_size):
    puzzle, _, gold = fixture()
    result = solve(puzzle, FakeClient(lambda clue: gold[clue["id"]]), batch_size=batch_size)
    check = next(r for r in result["trace"] if r["phase"] == "crosscheck")
    sizes = sorted(len(r["ids"]) for r in check["responses"] if r.get("mode") == "fill")
    assert sizes == [2, 4, 4]
    assert check["grid_before"] == gold and check["blind_answers"] == gold


def test_client_records_the_model_that_served_the_request(monkeypatch):
    import io

    from src.llm_client import Client

    monkeypatch.setenv("NEBIUS_API_KEY", "unit-test-placeholder")
    payload = {"model": "zai-org/GLM-5.3-Flash", "usage": {"total_tokens": 3},
               "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    monkeypatch.setattr("src.llm_client.urllib.request.urlopen",
                        lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
    assert Client().complete([])["served_model"] == "zai-org/GLM-5.3-Flash"


def test_crossing_answer_affected_by_a_crosscheck_fix_is_verified_again():
    puzzle, path, gold = fixture()

    class FixesOneSide(Anchored):
        """Crosscheck repair accepts the alternative for 1A only, leaving 1D in conflict."""

        def complete(self, messages, max_tokens=None):
            context = json.loads(messages[1]["content"])
            if context["mode"] == "repair":
                self.messages.append(messages)
                answers = {c["id"]: c["alternative"] if c["id"] == "1A" and "alternative" in c else c["answer"]
                           for c in context["clues"]}
                return {"text": json.dumps({"answers": answers}), "usage": {}}
            return super().complete(messages, max_tokens)

    client = FixesOneSide(gold)
    result = solve(puzzle, client)
    phases = [r["phase"] for r in result["trace"]]
    check = phases.index("crosscheck")
    # The conflicting crossing answer is removed, refilled and reviewed again before acceptance.
    assert "1D" in result["trace"][check]["removed"]
    reviewed_after_check = {k for r in result["trace"][check + 1:] if r["phase"] == "review"
                            for x in r["responses"] for k in x.get("ids", [])}
    assert {"1A", "1D"} <= reviewed_after_check
    assert phases[check + 1:] and phases[-1] == "review"
    assert result["termination"] == "complete_consistent_grid"
    assert evaluate(puzzle, result["answers"], path)["exact_solve"]
