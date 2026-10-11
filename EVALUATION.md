# Evaluation

This evaluation answers four questions:

1. What does each controller stage contribute?
2. Does the crosscheck step make the full controller more reliable?
3. How does batch size trade accuracy for cost?
4. How reliable is the full controller across stochastic runs?

It covers 50 standard puzzles the controller was not designed on, seven configurations and five runs of every configuration on every puzzle: 1,750 evaluated runs. The method, completion criteria and statistics were fixed before the runs in [`results/benchmark/evaluation_protocol.json`](results/benchmark/evaluation_protocol.json), together with hashes of the solver source, the runner and every puzzle.

## 1. Puzzle sets

**Development set (10 puzzles).** I designed and tuned the controller on these puzzles only:

- Eight Crossword Nexus puzzles (CC BY 4.0, included in the repository): *What A Fool Believes*, *I'm Alright*, *Gino (The Manager)*, *Garden Party*, *By George!*, *FM (A Grid Charlemagne Puzzle)*, *Jesus Children of America* and *The Cocoanuts*. *By George!* and *Gino (The Manager)* are deliberately hard themed puzzles built on catchphrases and invented wordplay.
- Two Crosshare puzzles reserved for development: *I'm Walkin' Here!* and *Themeless 136*.

**Evaluation set (50 puzzles).** Standard American 15×15 puzzles from Crosshare's curated featured list. Selection walked the list newest-first and kept the first 50 puzzles that passed every rule; nothing was picked by hand.

- **Structure:** 15×15 grid, 180° block symmetry, connected white cells, every cell in one Across and one Down entry, entries of at least three letters, one A–Z letter per cell, and clue numbers that match the grid.
- **No gimmicks:** no circled, shaded, barred, hidden or colored cells, and no rebus, meta, contest, cryptic or variety puzzles (by tags, styles, clue keywords and constructor notes).
- **Manual review of theme entries:** answers that are transformed (written backwards, or dropping a letter), joke-instruction cluing, and news-recap themes that need knowledge of recent events are out of scope.

Of the 108 full-size puzzles examined, 50 were selected, two were reserved for development and 56 were rejected:

| Rejection reason | Puzzles |
|---|---:|
| Excluded tag (meta, cryptic, contest, rebus, variety, colored cells, …) | 31 |
| Circled, shaded, barred or hidden cells | 13 |
| Asymmetric grid | 5 |
| Rebus cell (more than one letter) | 2 |
| Gimmick keyword in clues or notes | 1 |
| Manual review: answer-transforming theme | 2 |
| Manual review: joke-instruction cluing | 1 |
| Manual review: news-recap theme | 1 |

The 50 puzzles come from 27 constructors, contain 3,754 clues and 9,341 playable cells, and were published between 2026-05-07 and 2026-10-08; 48 of them appeared after GLM-5.3-Flash was released on 2026-08-26. Crosshare puzzles are "all rights reserved", so they are not included in this repository; [`data/benchmark/crosshare_heldout/selection_manifest.json`](data/benchmark/crosshare_heldout/selection_manifest.json) lists the selected puzzles, their hashes and every rejection with its reason.

## 2. Gold isolation

1. `Puzzle.load()` reads only the blank grid and clues.
2. `solve()` returns answers and a trace without seeing gold.
3. Only then does `evaluate()` open the separate gold file, check that it belongs to the same puzzle and is complete and crossing-consistent, and score the answers.

The solver uses no answer database, retrieval, candidate beam or constraint-satisfaction solver.

## 3. Configurations

Every configuration uses GLM-5.3-Flash (temperature 0.2, low reasoning effort), up to 15 rounds, 6,000 output tokens per request and a 400,000 reported-token threshold per run: new requests stop at the threshold, and requests already in flight can take reported usage slightly above it.

| Configuration | Behavior | Question |
|---|---|---|
| Single pass | One fill round on the empty grid, then conflict pruning. | What does the model alone achieve? |
| Fill loop | Fill repeatedly, using crossing letters as patterns, until a round changes nothing. A complete grid is accepted as is. | What does crossing feedback add? |
| + Repair | Adds repair of blocked regions. A complete grid is accepted without semantic review. | What does repair add? |
| Full controller without crosscheck | Adds semantic review and joint recheck. | What does review add? |
| **Full controller** | Adds the crosscheck step. Batches of 4. | What does crosscheck add? |
| Batch 1 | Full controller with one clue per request in fill, repair and review; requests in a round run four at a time against the round's starting state. The HTTP-attempt cap is 800 instead of 200, so the token threshold stays the binding limit. | Do smaller batches help? |
| Batch all + fallback | Full controller with all requested clues of a round in one request; incomplete responses fall back to the usual splitting. | Do larger batches help? |

The crosscheck pass always uses batches of four, so the batch comparison is about the main fill, repair and review requests.

**Crosscheck.** Once the grid is first verified, the model re-solves every clue without crossing letters. A crossing pair is flagged when an independent answer differs from the grid answer in one or two letters, including the shared cell; up to eight flagged pairs are rechecked jointly with both versions, and changed answers (and crossing answers whose shared letter changed) are reviewed again. If the rounds or the budget run out first, the last verified grid is submitted. A blank independent answer only means the model has no confident answer without letters; the check is recorded as `incomplete` when some clues got no response because a request hit the output limit, the budget or a transport failure.

Crosscheck settings were chosen on the development set; the evaluation set was not used for tuning.

## 4. Protocol

1. **Runs.** Every configuration ran five times on every puzzle, with the run index as the outer loop.
2. **Freezing.** Solver code, prompts, configurations, budgets and puzzles were fixed before the runs; every run records the source, runner and puzzle hashes, the configuration and the model that served each response.
3. **Resuming.** A run whose result was not saved is resumed with the same command. A saved run is reused only if its source, model, configuration and puzzle hashes match.
4. **Infrastructure errors.** A request that still failed after the client's HTTP retries is an infrastructure error. Such runs are archived and run again regardless of their outcome, up to three attempts in total; the kept attempt is the first one without infrastructure errors, or the third. Wrong answers, budget limits and round limits are never rerun.
5. **Completion.** 1,750 evaluated runs with no missing, duplicate or pending puzzle, infrastructure errors handled under the rule above, and every response served by the requested model.

## 5. Metrics and statistics

- **Primary: solved-puzzle rate.** A puzzle is solved when at least 3 of its 5 runs are exact solves (every clue matches gold and no crossing conflict remains). 95% intervals use the Wilson score method over puzzles.
- **Comparisons with the full controller.** Paired puzzle outcomes: exact McNemar test (a two-sided binomial test on puzzles solved by only one configuration) and a 95% interval for the difference in solved rates by Newcombe's (1998) method 10 for paired proportions (Wilson score intervals with a continuity-corrected correlation).
- **Secondary: exact solves per run.** The mean over puzzles of each puzzle's exact rate. Runs of the same puzzle are correlated, so intervals come from a puzzle-cluster bootstrap (10,000 resamples of puzzles with their five runs kept together); comparisons use per-puzzle differences with a paired cluster bootstrap interval and an exact sign test over puzzles.
- **Descriptive.** Clue and cell accuracy; false accepts (a submitted grid the controller had verified that is wrong); crosscheck status, coverage and the runs and clues it fixed or broke against gold; tokens (median, 90th percentile and total), HTTP calls and latency.

## 6. Results

The full generated tables are in [`results/benchmark/summary.md`](results/benchmark/summary.md). All 1,750 runs were completed with the frozen code; no run had an infrastructure error, so none was rerun, and all 153,088 responses were served by `zai-org/GLM-5.3-Flash`.

### Main results

| Configuration | Solved ≥3/5 [95% Wilson CI] | Exact solves per run [95% cluster CI] | Clue accuracy | False accepts (runs) | Median tokens | Median latency |
|---|---|---|---|---:|---:|---:|
| Single pass | 0/50: 0.0% [0.0, 7.1] | 0.0% [0.0, 0.0] | 72.6% | 0 | 18,742 | 44 s |
| Fill loop | 16/50: 32.0% [20.8, 45.8] | 32.0% [21.6, 42.8] | 94.5% | 19 | 34,452 | 91 s |
| + Repair | 42/50: 84.0% [71.5, 91.7] | 79.2% [70.8, 86.4] | 98.3% | 39 | 51,294 | 128 s |
| Full controller without crosscheck | 42/50: 84.0% [71.5, 91.7] | 85.2% [76.8, 92.4] | 98.2% | 20 | 84,780 | 188 s |
| **Full controller** | **46/50: 92.0% [81.2, 96.8]** | **90.0% [83.6, 95.2]** | **98.3%** | **13** | **106,434** | **227 s** |
| Batch 1 | 44/50: 88.0% [76.2, 94.4] | 86.4% [79.2, 92.8] | 98.3% | 13 | 156,390 | 306 s |
| Batch all + fallback | 47/50: 94.0% [83.8, 97.9] | 88.8% [82.8, 94.0] | 98.5% | 14 | 113,632 | 389 s |

### Paired comparisons with the full controller

Primary, on puzzle outcomes (solved or not):

| Configuration | Δ solved rate [95% Newcombe CI] | Puzzles worse / better / tied | Exact McNemar p |
|---|---|---|---|
| Single pass | −92.0 pp [−96.8, −79.0] | 46 / 0 / 4 | 2.8e−14 |
| Fill loop | −60.0 pp [−71.7, −43.5] | 30 / 0 / 20 | 1.9e−9 |
| + Repair | −8.0 pp [−18.5, +1.0] | 4 / 0 / 46 | 0.125 |
| Without crosscheck | −8.0 pp [−18.5, +1.0] | 4 / 0 / 46 | 0.125 |
| Batch 1 | −4.0 pp [−15.7, +7.2] | 4 / 2 / 44 | 0.69 |
| Batch all + fallback | +2.0 pp [−8.9, +13.2] | 2 / 3 / 45 | 1.0 |

Secondary, on exact solves per run (per-puzzle difference, puzzles resampled with their runs):

| Configuration | Δ exact solves per run [95% cluster CI] | Puzzles lower / higher / tied | Sign test p |
|---|---|---|---|
| Single pass | −90.0 pp [−95.2, −83.6] | 49 / 0 / 1 | 3.6e−15 |
| Fill loop | −58.0 pp [−68.0, −48.4] | 42 / 0 / 8 | 4.5e−13 |
| + Repair | −10.8 pp [−15.6, −6.4] | 20 / 1 / 29 | 2.1e−5 |
| Without crosscheck | −4.8 pp [−9.6, −0.8] | 10 / 3 / 37 | 0.092 |
| Batch 1 | −3.6 pp [−8.4, +0.8] | 11 / 6 / 33 | 0.33 |
| Batch all + fallback | −1.2 pp [−5.6, +2.8] | 7 / 6 / 37 | 1.0 |

### Crosscheck

| Configuration | Completed / incomplete / skipped / not reached | Clues answered / with a non-blank second opinion | Runs fixed (wrong → exact) | Runs broken (exact → wrong) |
|---|---|---|---:|---:|
| Full controller | 165 / 71 / 1 / 13 | 99.1% / 92.7% | 4 | 0 |
| Batch 1 | 158 / 68 / 0 / 24 | 99.4% / 93.1% | 2 | 0 |
| Batch all + fallback | 166 / 70 / 0 / 14 | 97.7% / 91.3% | 5 | 1 |

- In the full controller, crosscheck fixed four runs (nine clues) and broke none. Each fix replaced crossing answers that shared a wrong letter, like the development example in section 7. In a few runs the recheck switched a correct answer to the independent alternative, and the follow-up review switched it back before the grid was accepted.
- "Not reached" means the grid was never verified (out of budget); "incomplete" means some clues got no independent answer because a request hit the output limit (69 runs) or the output limit and the budget (2 runs).

### Cost

| Configuration | Total tokens | Requests per run (median) | Clues per request (mean) |
|---|---:|---:|---:|
| Full controller | 35.0M | 90 | 3.03 |
| Without crosscheck | 31.6M | 62 | 2.89 |
| Batch 1 | 48.0M | 210 | 1.25 |
| Batch all + fallback | 36.1M | 120 | 3.12 |

The benchmark used 192.6M provider-reported tokens over 1,750 runs. Because in-flight requests finish after the threshold is reached, 87 runs reported more than 400,000 tokens; the highest was 443,964 (11% above the threshold).

### Reliability and failures of the full controller

- 37 puzzles were solved in all five runs, 12 in some runs and 1 in none.
- Of its 25 non-exact runs, 13 were false accepts and 12 ran out of budget. Every false accept contains crossing answers that agree letter for letter but are wrong: in 12 a single crossing pair is the only error, and in one a chain of three answers. Crosscheck flagged 5 of these 13, but the joint recheck kept the wrong answers; in 6 the independent answer differed by more than two letters, so nothing was flagged; in 2 the independent answers were blank or repeated the mistake.
- The four puzzles below 3/5 were *Be Patient* and *Bright Ideas* (false accepts), *Trans critters* (before-and-after wordplay that exhausted the budget) and *Themeless #34*, a themeless puzzle with unusually many cross-references that no configuration solved in any run.

### Memorization probe

[`scripts/probe_memorization.py`](scripts/probe_memorization.py) gives the model only a puzzle's identity (title, author, source and date) and each slot's length, and asks for a guess in every slot. The model gave a valid guess for 3,065 of the 3,754 evaluation slots and recovered 1 correct answer; for the Crossword Nexus puzzles it guessed 504 of 626 slots and recovered none (one batch could not be parsed). This shows no sign that results rely on recalled solutions, although a probe of this kind cannot prove that no memorization exists.

## 7. Development set

The development runs used the same frozen code (full controller with and without crosscheck, 10 puzzles × 5 runs each):

| Configuration | Solved ≥3/5 [95% Wilson CI] | Exact solves per run | False accepts | Median / total tokens |
|---|---|---|---:|---|
| Full controller | 10/10 [72.2%, 100%] | 50/50 | 0 | 104,120 / 6.87M |
| Without crosscheck | 10/10 [72.2%, 100%] | 46/50 | 1 | 75,488 / 5.65M |

- Crosscheck fixed one run (a consistent wrong pair in *By George!*: ODIE / WOWDOW… → OWIE / WOWWOW…) and broke none. Of the four runs that failed without crosscheck, one was a consistent wrong pair the controller had accepted; the other three ran out of budget or rounds, so the 92% → 100% difference is not all due to crosscheck.
- The crosscheck pass got a response for 97.3% of clues and a non-blank independent answer for 91.1%. It was `incomplete` in 17 of 50 runs: 15 because some requests hit the output limit on hard themed clues, 1 because the budget ran out, and 1 for both reasons.
- The highest reported usage was 415,226 tokens (3.8% above the threshold). Crosscheck raised median tokens by 38% and total tokens by 21.5%.

## 8. Conclusions

1. **The controller, not the model alone, produces solved puzzles.** The model alone answers 72.6% of clues but solves no puzzle. Crossing feedback solves 32% of puzzles and repair raises that to 84%. Single pass and fill loop are far below the full controller (p < 10⁻⁸); with repair the gap narrows to 8 points.
2. **Crosscheck helps on balance, but the evidence is modest.** With crosscheck the full controller solves 46 of 50 puzzles instead of 42: four puzzles improve and none get worse (exact McNemar p = 0.125, so not significant at the 5% level with 50 puzzles). Per run, exact solves rise by 4.8 points [0.8, 9.6] (sign test p = 0.092), false accepts fall from 20 to 13 runs, and the traced changes fixed four runs and broke none. It costs 25% more median tokens and 11% more in total.
3. **Review mainly makes runs more reliable.** Adding review to repair leaves the solved rate at 84% but raises exact solves per run from 79.2% to 85.2% and halves false accepts (39 → 20). This comparison is descriptive; the planned tests compare every configuration with the full controller.
4. **Batch size changes cost more than accuracy.** Differences between batches of 1, 4 and all clues are within the uncertainty of 50 puzzles. Batches of four are the most economical: one clue per request uses 37% more total tokens (47% more per run at the median) and 2.3 times as many requests, and sending all clues at once is the slowest (median 389 s versus 227 s).
5. **The remaining failures are consistent-but-wrong crossings and budget.** Thirteen of the full controller's 25 failed runs accepted crossing answers that agree but are wrong (12 single pairs and one chain of three): crosscheck flagged five of them but the recheck kept the wrong answers, and the other eight were not flagged. The remaining 12 runs ran out of budget, eight of them on two puzzles.

## 9. Limitations

- **Scope.** One model and one puzzle source; Crosshare's featured puzzles are community-made and may differ from newspaper puzzles.
- **Repetition.** Five runs per puzzle estimate per-run reliability; they do not pin down rare failure modes.
- **Selection.** The evaluation set includes a manual review step for answer-transforming themes and news recaps; all exclusions are listed with their reasons.
- **Design.** The crosscheck step targets consistent-but-wrong crossing pairs, a failure type observed while developing the controller; its settings were chosen on the development set.
- **Batch definitions.** Batch 1 does not update crossings after each clue, and batch all relies on fallback splitting.
- **Token reporting.** Token counts are provider-reported; the threshold stops new requests rather than capping usage exactly.

## 10. Reproduce

The eight Crossword Nexus development puzzles and their runs are included, so every step below runs on them as is; because the two Crosshare development puzzles and the evaluation puzzles are not redistributed, the reproduced development tables cover 8 puzzles rather than the 10 in section 7.

```bash
python run_benchmark.py --puzzles data/benchmark/standard_15x15/puzzles data/benchmark/held_out/puzzles \
  --configs L3_full L3_no_crosscheck --runs 5 --workers 10 --out results/benchmark/development/runs
python analyze_benchmark.py --runs results/benchmark/development/runs \
  --puzzle-dirs data/benchmark/standard_15x15/puzzles data/benchmark/held_out/puzzles \
  --configs L3_full L3_no_crosscheck --out results/benchmark/development
```

`run_benchmark.py --rerun-infra-errors` applies the infrastructure-error rule, and `analyze_benchmark.py` refuses to summarize runs that are missing, duplicated, mixed across code or puzzle versions, or served by another model.
