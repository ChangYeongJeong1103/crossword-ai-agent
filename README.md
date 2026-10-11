# Crossword AI Agent

The goal of this project is to test whether a small controller can turn a general language model into a reliable solver for standard American 15×15 crosswords.

I kept the system deliberately simple:

- GLM-5.3-Flash proposes and reviews answers through Nebius Token Factory.
- Python controls the loop and handles the deterministic checks: answer lengths, crossing letters, conflict removal, retries and budgets.
- The model receives the same puzzle information a human receives. It never receives the gold solution and does not use an answer database.

## Results

I evaluated the agent on 50 standard 15×15 puzzles it was not designed on, with five runs of every configuration on every puzzle: 1,750 runs. A puzzle counts as solved when at least 3 of its 5 runs are exact solves; intervals are 95% Wilson intervals over puzzles.

| Configuration | Solved puzzles [95% CI] | Exact solves per run | Median tokens per run |
|---|---|---|---:|
| Model alone (single pass) | 0/50: 0.0% [0.0, 7.1] | 0.0% | 18,742 |
| + Crossing feedback (fill loop) | 16/50: 32.0% [20.8, 45.8] | 32.0% | 34,452 |
| + Repair | 42/50: 84.0% [71.5, 91.7] | 79.2% | 51,294 |
| + Semantic review | 42/50: 84.0% [71.5, 91.7] | 85.2% | 84,780 |
| **+ Crosscheck (full controller)** | **46/50: 92.0% [81.2, 96.8]** | **90.0%** | **106,434** |

- **The controller, not the model alone, produces solved puzzles.** The model alone answers 72.6% of clues but solves none of the 50 puzzles; crossing feedback and repair take the solved rate to 84%.
- **Crosscheck helps on balance.** It solves four more puzzles and loses none (exact McNemar p = 0.125, not significant at the 5% level with 50 puzzles), raises exact solves per run by 4.8 points [0.8, 9.6] and cuts false accepts from 20 to 13 runs, for 25% more median tokens. In the traced runs it fixed four and broke none.
- **Batch size changes cost more than accuracy.** Batches of 1, 4 and all clues are statistically indistinguishable. Batches of four are the most economical: one clue per request uses 37% more total tokens, and sending all clues at once is the slowest.
- **What still fails.** Of the full controller's 25 failed runs, 13 accepted crossing answers that agree letter for letter but are wrong (12 of them a single pair), and 12 ran out of budget. 37 puzzles were solved in every run; one themeless puzzle full of cross-references was solved in none.
- **No sign of memorization.** Given only a puzzle's identity and slot lengths, the model recovered 1 of 3,754 evaluation answers; 48 of the 50 puzzles were published after the model's release.
- **Model:** `zai-org/GLM-5.3-Flash`, which served all 153,088 responses. **Offline verification:** 96 tests.

Exactness is computed only after solving, against a separate gold file. The method and statistics were fixed before the runs; see [EVALUATION.md](EVALUATION.md) for the puzzle selection, configurations, all tables and limitations.

## Quick start

Python 3.11 or newer is required. The offline tests and recorded replays do not need an API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m streamlit run app.py
```

Live solving, `run_eval.py` and the benchmark scripts need Nebius credentials. Create a local `.env` file:

```text
NEBIUS_API_KEY=your_api_key_here
NEBIUS_MODEL=zai-org/GLM-5.3-Flash
```

The model line is optional. Never commit `.env`; `.gitignore` already excludes it.

## How the agent solves

1. **Load the puzzle.** Python validates the rectangular grid and builds the Across and Down entries, their lengths, cells and crossings.
2. **Fill missing entries.** The model receives batches of four clues, each with its required length and any letters already set by crossings.
3. **Validate proposals.** Python strips spaces, apostrophes and hyphens, rejects wrong lengths and pattern violations, and removes answers that create crossing conflicts.
4. **Retry efficiently.** Missing IDs and unparseable responses are retried without restarting the puzzle; an empty, length-limited batch is retried as individual clues.
5. **Repair blocked regions.** When progress stalls, the model reconsiders difficult entries together with their crossing clues. Existing letters stay tentative during repair.
6. **Review meaning.** After the grid is full, the model checks every answer against its clue. A grid is not accepted just because all letters cross consistently.
7. **Crosscheck.** Once the grid is verified, the model re-solves every clue without crossing letters. Where an independent answer differs from the grid answer in one or two letters at a crossing, the pair is rechecked with both versions, and changed answers are reviewed again. This targets a crossing pair that agrees letter for letter but is wrong.
8. **Evaluate separately.** Only after `solve()` returns does the evaluator open the gold file and compute exact, clue and cell accuracy.

**Stopping.** The controller runs up to four requests concurrently. It stops after a verified, crosschecked grid, or when it reaches 15 rounds, 200 HTTP attempts or 400,000 reported tokens (new requests stop at the threshold; requests already in flight can go slightly over). It then submits the last grid that passed verification, if there is one. HTTP 429 and transient server errors get bounded retries with backoff.

For a visual walkthrough of Fill → Repair → Review → Crosscheck and the gold boundary, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Puzzles

**Development set (10 puzzles).** I designed and tuned the controller on eight Crossword Nexus puzzles (CC BY 4.0, included with gold files) and two Crosshare puzzles, *I'm Walkin' Here!* and *Themeless 136*. Two of the Crossword Nexus puzzles, *By George!* and *Gino (The Manager)*, are deliberately hard themed puzzles built on catchphrases and invented wordplay.

**Evaluation set (50 puzzles).** Standard American 15×15 puzzles from Crosshare's curated featured list, taken newest-first by fixed rules: a symmetric, connected and fully checked grid; no circled, shaded or colored cells; no rebus, meta, cryptic or variety puzzles; and a review of theme entries that excludes answer-transforming themes and news-recap themes that need knowledge of recent events. Crosshare puzzles are "all rights reserved", so they are not included in this repository. The list records which puzzles were evaluated.

<details>
<summary>The 50 evaluation puzzles</summary>

| # | Puzzle | Constructor | Published |
|---:|---|---|---|
| 1 | [Visitor to children who have recently experienced a loss?](https://crosshare.org/crosswords/9cxdtDBHx94ejvHpc8tE) | Peaty n Oaty | 2026-10-08 |
| 2 | [Keep Your Eye on the Ballgame 261008](https://crosshare.org/crosswords/I1tiafCevmdJKjug0wXI) | Moose Dixon | 2026-10-06 |
| 3 | [The Witching Hour](https://crosshare.org/crosswords/Q0ZKSI2FvAm8ieyuzdkD) | Herman Chau | 2026-10-07 |
| 4 | [Themed Wednesday #19 - Change of Fortune](https://crosshare.org/crosswords/V3vUBf1TSD4CFVlBFndR) | The Puzzle Pit | 2026-10-04 |
| 5 | [Know Your Meme](https://crosshare.org/crosswords/AX9mYrlSCkBCS3dySePx) | crossbirds | 2026-10-06 |
| 6 | [Kangaroo](https://crosshare.org/crosswords/PcI2RV1pHWNLvNjNgdS7) | Marco Scibelli | 2026-10-06 |
| 7 | [In a Rage Room](https://crosshare.org/crosswords/WubIcuAOpI5z509UWVqq) | Jen Pissgirl | 2026-10-06 |
| 8 | [Teehee!](https://crosshare.org/crosswords/5vNf02sCzBMhgwq0JbgN) | xdes | 2026-10-06 |
| 9 | [Oct. 7 2026 Crossword: In Good Taste](https://crosshare.org/crosswords/FsXwUAHTThc3yLd7g11e) | Harry Zheng | 2026-10-05 |
| 10 | [October 1 2026](https://crosshare.org/crosswords/I45iFumRQqyrkoTbLH34) | Willamette Collegian | 2026-10-05 |
| 11 | [Broken Bones](https://crosshare.org/crosswords/aAluOf1mksk1ZIZmdjY2) | xdes | 2026-10-05 |
| 12 | [Metal Monday #72 - Themeless](https://crosshare.org/crosswords/HrWzJJLLYz75nFVFJtu1) | The Puzzle Pit | 2026-10-05 |
| 13 | [Themeless 15x15.](https://crosshare.org/crosswords/IxFrwllGnFQbuAqywLuy) | ElvenCatAccess | 2026-10-05 |
| 14 | [Trans critters](https://crosshare.org/crosswords/xHmCEsOubBqFf8TiszIS) | CeruleanK | 2026-10-04 |
| 15 | [Cool Cats](https://crosshare.org/crosswords/nC4FAvya5ytCQbckejB6) | xdes | 2026-10-04 |
| 16 | [Brunch Evite](https://crosshare.org/crosswords/jNj7hHHfZdqmYdH2t1rE) | Nebraska Public Media Labs | 2026-10-02 |
| 17 | [Physicist's Nightmare](https://crosshare.org/crosswords/2TDCb2vrPjfnF9DpZAIt) | Earth | 2026-10-02 |
| 18 | [🎶 Karen Carpenter and Phil Collins, among others 🎶](https://crosshare.org/crosswords/BQSM8Jl1zPEKa5xC5fbs) | Peaty n Oaty | 2026-10-02 |
| 19 | [1976](https://crosshare.org/crosswords/PoQ5Eai2SuIUjBdSapkN) | JeffsPuzzles | 2026-10-02 |
| 20 | [Pick a Card](https://crosshare.org/crosswords/3hP6JNKMyKSdaYdcrvJG) | Crossword Curiosities | 2026-09-23 |
| 21 | [Bizarro Tribute 261001](https://crosshare.org/crosswords/3OtijHE5IddDkmQ66hQW) | Moose Dixon | 2026-10-01 |
| 22 | [Autumn](https://crosshare.org/crosswords/JKOhW5Oxk1qXNHRMpz0X) | John Cowlishaw | 2026-09-30 |
| 23 | [Metal Monday #71 - "Mash-Ups"](https://crosshare.org/crosswords/F4h3Z1ADMuXzWODI34Pd) | The Puzzle Pit | 2026-09-28 |
| 24 | [Be Patient](https://crosshare.org/crosswords/qB4zC5LPVOZrPsBd0Hqb) | Nebraska Public Media Labs | 2026-09-23 |
| 25 | [Asimov's Three Laws of Robotics](https://crosshare.org/crosswords/c3lGlRzHZ8Si29lZpAg5) | John Cowlishaw | 2026-09-26 |
| 26 | [themeless 57](https://crosshare.org/crosswords/usFpIboAR3KWzQLZqMQK) | ghana7 | 2026-09-25 |
| 27 | [Themeless 137](https://crosshare.org/crosswords/cyvaRcL2FnMeiYXlFGo9) | JeffsPuzzles | 2026-09-25 |
| 28 | [Childhood Cuisine 260924](https://crosshare.org/crosswords/SjQFbZIsBhgIeE2OovGk) | Moose Dixon | 2026-09-03 |
| 29 | [This Puzzle Sucks](https://crosshare.org/crosswords/38WSnHVDDBSZaLHE9zkH) | Crossword Curiosities | 2026-07-31 |
| 30 | [Bright Ideas](https://crosshare.org/crosswords/ZPqisnPkDTHlm3KLcPEH) | crossbirds | 2026-09-21 |
| 31 | [On a Roll](https://crosshare.org/crosswords/hpvIR05lnptSmPBBM62w) | John Cowlishaw | 2026-09-21 |
| 32 | [Metal Monday #70 - Themeless](https://crosshare.org/crosswords/nh3BToabM0zRkDh7cXLd) | The Puzzle Pit | 2026-09-20 |
| 33 | [The Big Four](https://crosshare.org/crosswords/itBzKpOzVRtWBDJcFZMq) | Nebraska Public Media Labs | 2026-09-17 |
| 34 | [Can of Corn](https://crosshare.org/crosswords/KaErsAaTMOURSGNnAPky) | Trey Johnson | 2026-05-07 |
| 35 | [It’s Coming Down Hard](https://crosshare.org/crosswords/YoMXTvPVKcJmXBAe3Ljt) | txg88 | 2026-09-18 |
| 36 | [Face Value](https://crosshare.org/crosswords/uk0VO8JBu2ECzvLgFVzg) | Trey Johnson | 2026-09-18 |
| 37 | [Joe](https://crosshare.org/crosswords/rP9JWa3119Mua2ib6MKP) | John Cowlishaw | 2026-09-18 |
| 38 | [Out of Africa](https://crosshare.org/crosswords/2611sUM7irDbvVzsqHJm) | JeffsPuzzles | 2026-09-18 |
| 39 | [Newborns](https://crosshare.org/crosswords/MvSrn2yKtMh97gcp7EN8) | John Hopkins | 2026-09-17 |
| 40 | [September 16th, 2026 Crossword: The Big Bang](https://crosshare.org/crosswords/OeRu1jTTpnFWnUW79BW8) | Swecha Agarwal and Tavan Bhatia | 2026-09-13 |
| 41 | [Byran's Crosswords - #1](https://crosshare.org/crosswords/JjM8LtnHATgVNUbr3uzU) | Byran | 2026-09-16 |
| 42 | [Bird is the Word](https://crosshare.org/crosswords/SVMrAouNIcD42X1gNPYp) | The Tufts Daily | 2026-09-13 |
| 43 | [9/13/26 Puzzle](https://crosshare.org/crosswords/hKQEt9xVfGMT8OUH5k0E) | Shuuuze | 2026-09-13 |
| 44 | [Snake Charmers and Cat Burglars](https://crosshare.org/crosswords/yV02VXz9Y8UOuuFlvYBT) | Nebraska Public Media Labs | 2026-09-04 |
| 45 | [Say It Again](https://crosshare.org/crosswords/UdFK2ioptD6GARNdR6E4) | crossbirds | 2026-09-11 |
| 46 | [36A for making this puzzle](https://crosshare.org/crosswords/SQXiQ3ClGEt3UvYuErN6) | Asa Karon | 2026-09-08 |
| 47 | [Metal Monday #68 - Themeless](https://crosshare.org/crosswords/qrOGVlW41oaQ7eByCBZz) | The Puzzle Pit | 2026-09-06 |
| 48 | [More or Less](https://crosshare.org/crosswords/vj4fP4ctx6MEIHZVBDee) | John Cowlishaw | 2026-09-07 |
| 49 | [Defence of Fort M’Henry](https://crosshare.org/crosswords/iQUCPjBfH1rivm5LBrsm) | Nebraska Public Media Labs | 2026-09-02 |
| 50 | [Themeless #34](https://crosshare.org/crosswords/4bNxlP8fUltvTdhTTEoK) | SporcleMirror | 2026-09-05 |

</details>

The model receives only what a solver sees plus solver state: clue text, required length, puzzle title, current letter patterns, relevant crossing clues, long-clue context and explicit cross-references. The project uses the pretrained GLM-5.3-Flash model as provided by Nebius, without fine-tuning.

## Reproduce

**Solve one puzzle.** `run_eval.py` solves one puzzle, prints progress after each round and saves the full trace. Adding `--gold` turns on post-solve evaluation; the solver still never sees gold.

```bash
python run_eval.py \
  --puzzle data/benchmark/standard_15x15/puzzles/crossword_nexus_im_alright.json \
  --gold data/benchmark/standard_15x15/gold/crossword_nexus_im_alright.json
```

Optional arguments: `--model`, `--max-rounds`, `--max-tokens`, `--max-calls`, `--token-budget`. The defaults are in `src/config.py`.

**Run the benchmark.** `run_benchmark.py` runs configurations × puzzles × repeated runs on any folders of puzzles in this format, and `analyze_benchmark.py` produces the tables. The development puzzles are included; see [EVALUATION.md](EVALUATION.md#10-reproduce) for the exact commands. Saved runs are reused only when the source, model, configuration and puzzle hashes match.

## Demo

The Streamlit demo covers the eight bundled Crossword Nexus puzzles. It labels them with the split I used while designing the controller (six as development, two as evaluation); all eight belong to the development set described above.

- **Solve live** makes real Nebius API calls, uses credits and shows progress after every solver round. When the run finishes, the app evaluates the result and shows diagnostics.
- **Show recorded run** replays a saved run without a model call. For each puzzle it is the first exact solve among the five development runs of the full controller, so it shows a successful solve; per-puzzle success rates are in [EVALUATION.md](EVALUATION.md).

## Project structure

```text
crossword-ai-agent/
├── app.py                         # Streamlit live/replay demo
├── run_eval.py                    # Solve and evaluate one puzzle
├── run_benchmark.py               # Benchmark runner (configurations × puzzles × runs)
├── analyze_benchmark.py           # Completeness checks, intervals and paired tests
├── pyproject.toml                 # Package, dependency and test configuration
├── src/
│   ├── puzzle.py                  # Grid validation, entries and crossings
│   ├── solver.py                  # Fill, repair, review, crosscheck and trace loop
│   ├── llm_client.py              # Nebius client, retries and budgets
│   ├── config.py                  # Default configuration
│   └── evaluator.py               # Post-solve comparison with gold
├── scripts/
│   └── probe_memorization.py      # Recall probe without clues
├── tests/
│   ├── test_solver.py             # Offline controller tests
│   └── test_benchmark.py          # Offline benchmark runner and statistics tests
├── data/
│   ├── benchmark/
│   │   ├── standard_15x15/        # Development puzzles and gold (Crossword Nexus)
│   │   ├── held_out/              # Development puzzles and gold (Crossword Nexus)
│   │   └── crosshare_heldout/     # Crosshare manifest: evaluation and development puzzles
│   └── synthetic/                 # Small deterministic test fixture
└── results/
    ├── benchmark/
    │   ├── evaluation_protocol.json   # Method, hashes and rules fixed before the runs
    │   ├── summary.{md,json}          # Evaluation results
    │   └── development/               # Development results and Crossword Nexus runs
    ├── crossword_nexus_*.json         # Demo replays
    └── held_out/                      # Demo replays
```

Supporting documents:

- [EVALUATION.md](EVALUATION.md): methodology, results and limitations
- [ARCHITECTURE.md](ARCHITECTURE.md): visual solver flow and gold boundary
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md): source attribution and licensing

## What I intentionally did not add

- No answer retrieval or crossword answer database.
- No model substitution, candidate beam or constraint-satisfaction solver.
- No gold access before the solver returns.
- `complete_consistent_grid` is a controller status, not proof of exactness.

The design was informed by "Language Models are Crossword Solvers" (Saha et al., NAACL 2025), but I wrote this controller independently. It is not a SweepClip reproduction.

## Limitations

- **Scope.** One model and one puzzle source (Crosshare community puzzles); results may differ for newspaper puzzles or other models. With 50 puzzles, differences of a few puzzles are within the uncertainty.
- **Stochastic output.** The full controller solves 90% of runs exactly; repeated runs can take different time and tokens or return a different grid.
- **Review gaps.** A crossing pair that agrees letter for letter but is wrong is still the main failure; crosscheck catches some of them, not all.
- **Cost.** The full controller uses a median of 106k tokens and about four minutes per puzzle. The 400,000-token threshold stops new requests, but requests already in flight can exceed it (the highest run reported 443,964).
- **Usage reporting.** Token counts are provider-reported.

The Crossword Nexus fixtures are distributed under CC BY 4.0, and the Crosshare puzzles are not redistributed. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for authors, source links and attribution.
