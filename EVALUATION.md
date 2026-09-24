# Evaluation

I used this evaluation to measure whether the controller could turn clue proposals into an exact crossword solution, not just a full-looking grid. The saved runs also show how the controller progressed and how much each puzzle cost.

## 1. What I measured

The primary metric is exact solve: every clue must match the separate gold solution with no crossing conflicts. I also track clue accuracy, cell accuracy, coverage, conflicts, termination reason, calls, reported tokens and runtime. The development/evaluation split tests whether the controller transfers beyond the five puzzles used while I was building it.

## 2. Puzzle set

I selected seven standard American 15×15 crosswords from Crossword Nexus under CC BY 4.0. Each fixture has:

- A puzzle JSON containing the blank grid, title, clue IDs, clue text, directions, lengths and starting cells.
- A separate gold JSON containing the completed answers.
- Source metadata including author, publication date, source URL, source format and SHA-256.

Benchmark selection required a 15×15 grid, 180° block symmetry, connected white cells, fully checked entries and a minimum entry length of three.

The runtime loader does not enforce 15×15. It verifies rectangular shape, slot positions and lengths, block boundaries, cell coverage and duplicate directions. The synthetic 5×5 fixture is used only for deterministic tests.

The solver uses the pretrained GLM-5.3-Flash model through Nebius Token Factory. I did not fine-tune the model.

### Development set

I used five puzzles during controller development:

- What A Fool Believes
- I'm Alright
- Gino (The Manager)
- Garden Party
- By George!

These results measure development performance, not unseen-puzzle generalization.

I selected **By George!** and **Gino (The Manager)** from the start as difficult themed stress tests alongside the more conventional puzzles. By George! contains creator-specific catchphrases and repeated words. Gino contains invented name-based wordplay. I wanted to test whether clue semantics and crossing feedback could recover answers that do not look like ordinary standalone dictionary words.

### Evaluation set

I reserved two puzzles for final evaluation:

- Jesus Children of America
- The Cocoanuts

I reran each selected evaluation puzzle once with the final source and settings. The reported artifacts are those completed reruns. I did not change the puzzle selection or tune the controller from these results.

The set definitions and frozen settings are recorded in:

- `data/benchmark/standard_15x15/selection_manifest.json`
- `data/benchmark/held_out/selection_manifest.json`
- `data/benchmark/held_out/evaluation_protocol.json`

## 3. Gold isolation

Gold answers are not loaded by the puzzle class, included in prompts or available to the solver.

The execution boundary is:

1. `Puzzle.load()` reads only the blank grid and clues.
2. `solve()` returns predicted answers and a trace.
3. Only then does `evaluate()` open the separate gold file.
4. The evaluator verifies that the gold belongs to the same puzzle and is complete, structurally valid and crossing-consistent.
5. The evaluator compares predicted clues and rendered cells with gold.

The solver uses no answer database, external answer retrieval, puzzle-specific answer list, model substitution, candidate beam or constraint-satisfaction solver.

## 4. Run protocol

I used the following protocol for a reportable run:

1. Select the puzzle before inference.
2. Freeze the Python source and solver configuration.
3. Record the SHA-256 of all Python files under `src/`.
4. Run one puzzle with its puzzle JSON only.
5. Save every model response, accepted change, rejected proposal, removed conflict, error, usage report and round summary.
6. Stop on a semantically reviewed consistent grid or a configured round, call or token limit.
7. Load gold only after solving and calculate the metrics below.
8. Save the result, run budgets, timestamp and source hash as one JSON artifact. Keep the full frozen configuration in the evaluation metadata.
9. Report every completed evaluation run rather than selecting the best completed run.

This report measures one completed run per puzzle, not pass probability. A stronger reliability study would freeze a larger unseen set and run every puzzle multiple times.

## 5. Metrics

### Exact solve

`exact_solve` is true only when every predicted clue equals its gold answer and no crossing conflict remains. This is the primary metric.

### Clue accuracy

The number of exactly correct clue answers divided by the total number of clues. Missing and malformed answers count as incorrect.

### Cell accuracy

The number of correct playable cells divided by the total number of playable cells. Blocks are excluded. A blank or conflicted cell counts as incorrect.

### Coverage and conflicts

Coverage is the fraction of clues with a valid normalized answer. Conflicts count crossing pairs whose letters disagree.

### Controller termination

`complete_consistent_grid` means that the controller filled the grid, found no crossing conflict and recorded semantic confirmation for every entry. It is not proof of correctness; only the separate evaluator can establish an exact solve.

Other termination reasons include `budget_limit`, `round_limit` and `stalled`.

### Resource usage

Each result records HTTP attempts, provider-reported tokens and wall-clock latency. Requests already in progress may take usage slightly above the configured token threshold. A failed request without a usable provider response may not expose billable usage.

## 6. Frozen reported configuration

- Model: `zai-org/GLM-5.3-Flash`
- Temperature: 0.2
- Reasoning effort: low
- Maximum rounds: 12
- Clues per batch: 4
- Concurrent requests per puzzle: 4
- Output limit: 6,000 tokens per request
- Singleton retry limit: 12,000 tokens
- HTTP-attempt limit: 200 per puzzle
- Reported-token threshold: 400,000 per puzzle

The seven official recorded artifacts were generated with core source SHA-256:

`a542fd543d2ede631a0ee957d7f159ddda3d194c01b6d781025d2a4c017e1423`

This is also the hash of the final source in this repository.

## 7. Results

### Combined summary

- Exact solves: **7/7**
- Correct clues: **548/548**
- Correct cells: **1,314/1,314**
- Development: **5/5 exact**
- Evaluation: **2/2 exact**

### Development results

**I'm Alright**

- Exact: Yes
- Clues: 78/78
- Cells: 189/189
- Termination: `complete_consistent_grid`
- Calls: 54
- Reported tokens: 64,171
- Runtime: 311.2 seconds

**Garden Party**

- Exact: Yes
- Clues: 78/78
- Cells: 187/187
- Termination: `complete_consistent_grid`
- Calls: 48
- Reported tokens: 44,500
- Runtime: 112.4 seconds

**What A Fool Believes**

- Exact: Yes
- Clues: 78/78
- Cells: 185/185
- Termination: `complete_consistent_grid`
- Calls: 55
- Reported tokens: 71,102
- Runtime: 247.3 seconds

**By George! — themed stress test**

- Exact: Yes
- Clues: 78/78
- Cells: 191/191
- Termination: `complete_consistent_grid`
- Calls: 151
- Reported tokens: 368,790
- Runtime: 1,942.6 seconds

**Gino (The Manager) — themed stress test**

- Exact: Yes
- Clues: 80/80
- Cells: 189/189
- Termination: `complete_consistent_grid`
- Calls: 137
- Reported tokens: 336,042
- Runtime: 1,284.2 seconds

### Evaluation results

**Jesus Children of America**

- Exact: Yes
- Clues: 78/78
- Cells: 183/183
- Termination: `complete_consistent_grid`
- Calls: 43
- Reported tokens: 36,358
- Runtime: 43.1 seconds

**The Cocoanuts**

- Exact: Yes
- Clues: 78/78
- Cells: 190/190
- Termination: `complete_consistent_grid`
- Calls: 59
- Reported tokens: 73,944
- Runtime: 248.2 seconds

## 8. Verification and reproducibility

I used the following checks:

- 21 deterministic offline tests pass.
- I recomputed all seven official scores from their saved answers and separate gold files.
- All seven official artifacts share the frozen source hash above; their saved grids, metrics and run-budget fields were cross-checked.
- Recorded replay mode was checked with model network calls blocked.
- Every official result JSON retains raw model responses and round traces.

Run the offline suite:

```bash
python -m pytest
```

Reproduce the evaluation pipeline for one puzzle:

```bash
python run_eval.py \
  --puzzle data/benchmark/held_out/puzzles/crossword_nexus_jesus_children_of_america.json \
  --gold data/benchmark/held_out/gold/crossword_nexus_jesus_children_of_america.json
```

This command uses the same source and configuration as the recorded results. The model is stochastic, so a new run may still differ.

## 9. What the results support

The frozen runs reached 7/7 exact solves, including 2/2 on the reserved evaluation set. The two stress tests also show that the loop can recover unconventional themed entries from clues and crossings rather than relying only on word plausibility.

The evidence remains limited:

- The evaluation set contains only two puzzles.
- Development-set accuracy is not a generalization measurement.
- Each reported puzzle has one completed stochastic run, so the report does not estimate solve probability.
- The two themed stress tests are harder and less representative of ordinary fill.
- A mutually consistent but semantically wrong region can survive until review.
- Runtime and provider-reported usage vary substantially between repeated runs.

Current official development artifacts are stored directly under `results/`. Official evaluation artifacts are stored under `results/held_out/`.
