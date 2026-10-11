Puzzle solved: at least 3 exact solves in 5 runs. Puzzles with unfinished runs are excluded from the solved rate and paired comparisons.

| Config | Runs | Completed / pending puzzles | Solved ≥3/5 [95% Wilson CI] | Exact solve / run [95% cluster CI] | Clue accuracy | Cell accuracy | False accept | Tokens median / p90 | Tokens per exact | HTTP calls median | Latency median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L0_single_pass | 250 | 50 / 0 | 0/50: 0.0% [0.0%, 7.1%] | 0.0% [0.0%, 0.0%] | 72.6% [69.5%, 75.3%] | 89.6% [87.0%, 91.8%] | 0 | 18,742 / 39,444 | — | 23 | 44s |
| L1_fill_loop | 250 | 50 / 0 | 16/50: 32.0% [20.8%, 45.8%] | 32.0% [21.6%, 42.8%] | 94.5% [92.4%, 96.2%] | 97.9% [96.6%, 98.8%] | 19 | 34,452 / 119,112 | 179,375 | 34 | 91s |
| L2_fill_repair | 250 | 50 / 0 | 42/50: 84.0% [71.5%, 91.7%] | 79.2% [70.8%, 86.4%] | 98.3% [96.2%, 99.5%] | 99.0% [97.5%, 99.9%] | 39 | 51,294 / 208,475 | 110,051 | 40 | 128s |
| L3_full | 250 | 50 / 0 | 46/50: 92.0% [81.2%, 96.8%] | 90.0% [83.6%, 95.2%] | 98.3% [95.9%, 99.8%] | 99.0% [97.4%, 99.9%] | 13 | 106,434 / 296,451 | 155,586 | 90 | 227s |
| L3_no_crosscheck | 250 | 50 / 0 | 42/50: 84.0% [71.5%, 91.7%] | 85.2% [76.8%, 92.4%] | 98.2% [95.7%, 99.6%] | 99.0% [97.3%, 99.9%] | 20 | 84,780 / 263,281 | 148,422 | 62 | 188s |
| L3_batch1 | 250 | 50 / 0 | 44/50: 88.0% [76.2%, 94.4%] | 86.4% [79.2%, 92.8%] | 98.3% [95.7%, 99.7%] | 99.0% [97.3%, 99.9%] | 13 | 156,390 / 401,723 | 222,045 | 210 | 306s |
| L3_batch_all | 250 | 50 / 0 | 47/50: 94.0% [83.8%, 97.9%] | 88.8% [82.8%, 94.0%] | 98.5% [96.4%, 99.7%] | 99.1% [97.7%, 99.9%] | 14 | 113,632 / 300,118 | 162,675 | 120 | 389s |

| Config | Tokens total | Requests per run (median) | Clues per request (mean) | Split fallbacks per run (mean) | Verified grid submitted (termination) |
|---|---|---|---|---|---|
| L0_single_pass | 5,749,281 | 23 | 3.34 | 1.2 | 0 (—) |
| L1_fill_loop | 14,349,965 | 34 | 2.90 | 3.3 | 99 (complete_consistent_grid 99) |
| L2_fill_repair | 21,790,086 | 40 | 2.65 | 5.5 | 237 (complete_consistent_grid 237) |
| L3_full | 35,006,749 | 90 | 3.03 | 6.9 | 237 (complete_consistent_grid 236, round_limit 1) |
| L3_no_crosscheck | 31,613,947 | 62 | 2.89 | 6.5 | 233 (complete_consistent_grid 233) |
| L3_batch1 | 47,961,631 | 210 | 1.25 | 1.4 | 226 (complete_consistent_grid 226) |
| L3_batch_all | 36,113,887 | 120 | 3.12 | 4.6 | 236 (complete_consistent_grid 236) |

| Config vs L3_full | Puzzles | Δ solved-puzzle rate [95% Newcombe CI] | Puzzles worse | Puzzles better | Tied | Exact McNemar p |
|---|---|---|---|---|---|---|
| L0_single_pass | 50 | -92.0% [-96.8%, -79.0%] | 46 | 0 | 4 | 2.84e-14 |
| L1_fill_loop | 50 | -60.0% [-71.7%, -43.5%] | 30 | 0 | 20 | 1.86e-09 |
| L2_fill_repair | 50 | -8.0% [-18.5%, +1.0%] | 4 | 0 | 46 | 0.125 |
| L3_no_crosscheck | 50 | -8.0% [-18.5%, +1.0%] | 4 | 0 | 46 | 0.125 |
| L3_batch1 | 50 | -4.0% [-15.7%, +7.2%] | 4 | 2 | 44 | 0.688 |
| L3_batch_all | 50 | +2.0% [-8.9%, +13.2%] | 2 | 3 | 45 | 1 |

| Config vs L3_full (secondary) | Puzzles | Δ exact solves per run [95% cluster CI] | Puzzles lower | Puzzles higher | Tied | Sign test p |
|---|---|---|---|---|---|---|
| L0_single_pass | 50 | -90.0% [-95.2%, -83.6%] | 49 | 0 | 1 | 3.55e-15 |
| L1_fill_loop | 50 | -58.0% [-68.0%, -48.4%] | 42 | 0 | 8 | 4.55e-13 |
| L2_fill_repair | 50 | -10.8% [-15.6%, -6.4%] | 20 | 1 | 29 | 2.1e-05 |
| L3_no_crosscheck | 50 | -4.8% [-9.6%, -0.8%] | 10 | 3 | 37 | 0.0923 |
| L3_batch1 | 50 | -3.6% [-8.4%, +0.8%] | 11 | 6 | 33 | 0.332 |
| L3_batch_all | 50 | -1.2% [-5.6%, +2.8%] | 7 | 6 | 37 | 1 |

| Config | Crosscheck completed / incomplete / skipped / not reached | Clues answered / with a second opinion | Runs fixed (wrong → exact) | Runs broken (exact → wrong) | Clues fixed / broken |
|---|---|---|---|---|---|
| L3_full | 165 / 71 / 1 / 13 | 99.1% / 92.7% | 4 | 0 | 9 / 0 |
| L3_batch1 | 158 / 68 / 0 / 24 | 99.4% / 93.1% | 2 | 0 | 4 / 0 |
| L3_batch_all | 166 / 70 / 0 / 14 | 97.7% / 91.3% | 5 | 1 | 12 / 2 |

| Config | Puzzles solved in every run | In some runs | In no run |
|---|---|---|---|
| L0_single_pass | 0 | 0 | 50 |
| L1_fill_loop | 7 | 19 | 24 |
| L2_fill_repair | 26 | 22 | 2 |
| L3_full | 37 | 12 | 1 |
| L3_no_crosscheck | 35 | 14 | 1 |
| L3_batch1 | 34 | 15 | 1 |
| L3_batch_all | 34 | 15 | 1 |

Evaluated runs: 1,750. Attempts archived for infrastructure errors: 0. Runs kept with residual infrastructure errors: 0. Tokens across all attempts: 192,585,546.

| Memorization probe set | Puzzles | Slots | Attempted | Recalled correctly |
|---|---|---|---|---|
| crosshare | 50 | 3754 | 3065 | 1 (0.0%) |
| crossword_nexus | 8 | 626 | 504 | 0 (0.0%) |
