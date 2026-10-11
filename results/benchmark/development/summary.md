Puzzle solved: at least 3 exact solves in 5 runs. Puzzles with unfinished runs are excluded from the solved rate and paired comparisons.

| Config | Runs | Completed / pending puzzles | Solved ≥3/5 [95% Wilson CI] | Exact solve / run [95% cluster CI] | Clue accuracy | Cell accuracy | False accept | Tokens median / p90 | Tokens per exact | HTTP calls median | Latency median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L3_full | 50 | 10 / 0 | 10/10: 100.0% [72.2%, 100.0%] | 100.0% [100.0%, 100.0%] | 100.0% [100.0%, 100.0%] | 100.0% [100.0%, 100.0%] | 0 | 104,120 / 300,135 | 137,455 | 86 | 196s |
| L3_no_crosscheck | 50 | 10 / 0 | 10/10: 100.0% [72.2%, 100.0%] | 92.0% [82.0%, 100.0%] | 99.6% [99.2%, 100.0%] | 99.9% [99.7%, 100.0%] | 1 | 75,488 / 297,094 | 122,928 | 62 | 123s |

| Config | Tokens total | Requests per run (median) | Clues per request (mean) | Split fallbacks per run (mean) | Verified grid submitted (termination) |
|---|---|---|---|---|---|
| L3_full | 6,872,733 | 86 | 3.08 | 6.5 | 50 (complete_consistent_grid 50) |
| L3_no_crosscheck | 5,654,670 | 62 | 2.99 | 5.7 | 47 (complete_consistent_grid 47) |

| Config vs L3_full | Puzzles | Δ solved-puzzle rate [95% Newcombe CI] | Puzzles worse | Puzzles better | Tied | Exact McNemar p |
|---|---|---|---|---|---|---|
| L3_no_crosscheck | 10 | +0.0% [-27.8%, +27.8%] | 0 | 0 | 10 | 1 |

| Config vs L3_full (secondary) | Puzzles | Δ exact solves per run [95% cluster CI] | Puzzles lower | Puzzles higher | Tied | Sign test p |
|---|---|---|---|---|---|---|
| L3_no_crosscheck | 10 | -8.0% [-16.0%, +0.0%] | 3 | 0 | 7 | 0.25 |

| Config | Crosscheck completed / incomplete / skipped / not reached | Clues answered / with a second opinion | Runs fixed (wrong → exact) | Runs broken (exact → wrong) | Clues fixed / broken |
|---|---|---|---|---|---|
| L3_full | 33 / 17 / 0 / 0 | 97.3% / 91.1% | 1 | 0 | 2 / 0 |

| Config | Puzzles solved in every run | In some runs | In no run |
|---|---|---|---|
| L3_full | 10 | 0 | 0 |
| L3_no_crosscheck | 7 | 3 | 0 |

Evaluated runs: 100. Attempts archived for infrastructure errors: 0. Runs kept with residual infrastructure errors: 0. Tokens across all attempts: 12,527,403.
