# Crossword AI Agent

The goal of this project is to test whether a small controller can turn a general language model into a reliable solver for standard American 15×15 crosswords.

I kept the system deliberately simple. GLM-5.3-Flash proposes and reviews answers through Nebius Token Factory. Python controls the loop and handles deterministic checks: answer lengths, crossing letters, conflict removal, retries and budgets. The model receives the same puzzle information a human receives. It does not receive the gold solution or use an answer database.

The development loop was:

```text
run puzzles → inspect failures → change one controller behavior → rerun the same fixed set
```

## Headline results

- **Development set:** 5/5 exact solves, 392/392 clues and 941/941 cells.
- **Evaluation set:** 2/2 exact solves, 156/156 clues and 373/373 cells.
- **Combined recorded results:** 7/7 exact solves.
- **Model:** `zai-org/GLM-5.3-Flash`.
- **Offline verification:** 21 controller and fixture tests.

These are measured saved runs, not a guarantee that every stochastic run will produce the same result. I calculate exactness only after solving by comparing the returned answers with a separate gold file.

See [EVALUATION.md](EVALUATION.md) for the full methodology, per-puzzle results, source hashes and limitations.

## Quick start

Python 3.11 or newer is required. The offline tests and recorded replay do not need an API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m streamlit run app.py
```

Only **Solve live** and `run_eval.py` need Nebius credentials. For those modes, create a local `.env` file:

```text
NEBIUS_API_KEY=your_api_key_here
NEBIUS_MODEL=zai-org/GLM-5.3-Flash
```

The model line is optional. Never commit `.env`; it is excluded by `.gitignore`.

## What the experiments showed

- **Crossing consistency is necessary but not sufficient.** A complete grid can still contain a mutually consistent wrong region, so the controller reviews clue meaning after filling the grid.
- **Empty model responses were the main token failure.** Some calls spent their output budget on reasoning and returned no JSON. Retrying length-limited batches as individual clues removed the most expensive recursive retry path.
- **The themed stress tests remained expensive.** The agent solved both exactly, but they required far more calls and tokens than the conventional puzzles.

## Demo

I kept the Streamlit demo explicit about whether it is making a real model call:

- **Solve live** makes real Nebius API calls, uses credits and shows progress after every solver round. When the run finishes, the app evaluates the result and displays diagnostics.
- **Show recorded run** instantly replays an existing result from `results/`. It makes no model call and is explicitly labeled as a replay.

Every result shows clue accuracy, cell accuracy, exact-solve status, calls, reported tokens, runtime and round-level diagnostics. Live JSON files can also be downloaded from the app.

## How the agent solves

1. **Load the puzzle.** Python validates the rectangular grid and builds Across and Down entries, lengths, cells and crossings.
2. **Fill missing entries.** The model receives small batches containing each clue, required length and any letters already supplied by crossings.
3. **Validate proposals.** Python strips spaces, apostrophes and hyphens, rejects wrong lengths or pattern violations, and removes answers that create crossing conflicts.
4. **Retry efficiently.** Missing IDs and unparseable responses are retried without restarting the puzzle. Answers with invalid characters, lengths or patterns are rejected and reconsidered in a later round. An empty length-limited batch is retried directly as individual clues.
5. **Repair blocked regions.** When progress stalls, the model reconsiders difficult entries together with their crossing clues. Existing letters remain tentative during repair.
6. **Review meaning.** After the grid is full, the model checks every answer against its clue. A grid is not accepted merely because all letters cross consistently.
7. **Evaluate separately.** Only after `solve()` returns does the evaluator open the gold file and calculate exact, clue and cell accuracy.

The controller uses batches of four clues and up to four concurrent requests. It stops after a verified complete grid or after reaching the configured round, call or token budget. HTTP 429 and transient server errors receive bounded retries with backoff.

For a visual walkthrough of Fill → Repair → Review and the gold boundary, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Puzzle set

I selected five development puzzles and two evaluation puzzles from Crossword Nexus. All are standard 15×15 American-style grids with separate puzzle and gold files.

Benchmark selection required a 15×15 grid, 180° block symmetry, connected white cells, fully checked entries and a minimum entry length of three. The runtime loader is size-agnostic: it validates rectangular shape, slot positions and lengths, block boundaries, cell coverage and duplicate directions. This is why the same code can load the synthetic 5×5 test fixture.

I included **By George!** and **Gino (The Manager)** in the development set from the start as difficult themed stress tests. They contain creator-specific catchphrases, repeated words and invented name-based wordplay rather than only ordinary fill.

The model receives only puzzle-visible and solver-state context: clue text, required length, puzzle title, current letter patterns, relevant crossing and long-clue context, and explicit cross-references. It never receives gold answers. The recorded runs solved both stress tests exactly, which is the main evidence that the clue-and-crossing loop can recover unconventional themed answers without exposing gold.

The synthetic fixture is used only for deterministic tests. The five development puzzles were used while designing the strategy, while the two evaluation puzzles were run after the configuration was finalized. I did not tune the controller from their completed results.

The project uses the pretrained GLM-5.3-Flash model as provided by Nebius. I did not fine-tune the model. Dataset provenance and selection metadata are stored beside the fixtures.

## Reproduce one run from the CLI

`run_eval.py` solves one puzzle, prints progress after each round and saves the complete trace. Supplying `--gold` enables post-solve evaluation; it does not expose gold to the solver.

```bash
python run_eval.py \
  --puzzle data/benchmark/standard_15x15/puzzles/crossword_nexus_im_alright.json \
  --gold data/benchmark/standard_15x15/gold/crossword_nexus_im_alright.json
```

Optional arguments include `--model`, `--max-rounds`, `--max-tokens`, `--max-calls` and `--token-budget`. The reported configuration uses 12 rounds, 6,000 output tokens per request, 200 HTTP attempts and a 400,000 reported-token threshold per puzzle. A request that starts as a singleton may receive one attempt with up to 12,000 output tokens. Already-running requests may take reported usage slightly above the threshold.

## Project structure

```text
crossword-ai-agent/
├── app.py                         # Streamlit live/replay demo
├── run_eval.py                    # CLI solver and evaluator
├── pyproject.toml                 # Package, dependency and test configuration
├── src/
│   ├── puzzle.py                  # Grid validation, entries and crossings
│   ├── solver.py                  # Fill, repair, review and trace loop
│   ├── llm_client.py              # Nebius client, retries and budgets
│   └── evaluator.py               # Post-solve comparison with gold
├── tests/
│   └── test_solver.py             # Offline deterministic tests
├── data/
│   ├── benchmark/
│   │   ├── standard_15x15/        # Five development puzzles and gold
│   │   └── held_out/              # Two evaluation puzzles and gold
│   └── synthetic/                 # Small deterministic test fixture
└── results/
    ├── crossword_nexus_*.json     # Five recorded development runs
    └── held_out/                  # Recorded evaluation runs
```

Supporting documents:

- [EVALUATION.md](EVALUATION.md) — methodology, results and limitations.
- [ARCHITECTURE.md](ARCHITECTURE.md) — visual solver flow and gold boundary.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — source attribution and licensing.

## What I intentionally did not add

- No answer retrieval or crossword answer database.
- No model substitution, candidate beam or constraint-satisfaction solver.
- No gold access before the solver returns.
- Gold files remain in the repository only for reproducible post-solve scoring.
- `complete_consistent_grid` is a controller status, not proof of exactness.

The design was informed by “Language Models are Crossword Solvers” (Saha et al., NAACL 2025), but I wrote this controller independently. It is not a SweepClip reproduction.

## Limitations

- The evaluation set contains only two puzzles, so it does not establish universal accuracy.
- Model output is stochastic; repeated live runs can use different time and tokens or return a different grid.
- Difficult themed puzzles can require substantially more calls than conventional fill.
- Provider-reported usage may omit failed requests that return no usable response.
- Live solving uses API credits and can take several minutes.

Puzzle fixtures are distributed under CC BY 4.0. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for authors, source links and attribution.
