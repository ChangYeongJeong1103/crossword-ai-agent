# Exploratory reviewer trial

GLM-5.3-Flash remains the default for all stages and the basis of the [main evaluation](../../../EVALUATION.md). This folder preserves a side experiment with a different reviewer.

**Completed on October 26, 2026 (Pacific time): three public development puzzles, one fresh run per reviewer, six live API runs.** The puzzles are *I'm Alright*, *FM (A Grid Charlemagne Puzzle)* and *Garden Party*, all included under CC BY 4.0. The difficult theme puzzles *By George!* and *Gino* were excluded. This pilot is separate from the main 50-puzzle evaluation and its 3-of-5 solved-puzzle rule.

Both configurations use GLM-5.3-Flash for fill, repair and crosscheck. Semantic review changes from GLM-5.3-Flash to `nvidia/Nemotron-3.5-Super-VL`. Both were run with the same source version, prompts, batch size 4, temperature 0.2, 15 rounds, 6,000 output tokens per request, 200 HTTP attempts and a shared 400,000-token threshold. GLM uses low reasoning effort; Nemotron has no explicit reasoning override. Puzzles ran one at a time, with up to four requests in parallel inside a round; reviewer order alternated across puzzles.

| Metric | GLM review | Nemotron review |
|---|---:|---:|
| Puzzles / fresh runs | 3 / 3 | 3 / 3 |
| Exact solves | 3/3 | 3/3 |
| Clue / cell accuracy | 100% / 100% | 100% / 100% |
| False accepts | 0 | 0 |
| Median total tokens per run | 59,696 | 134,343 |
| Median review-request tokens per run | 27,806 | 94,957 |
| Median latency per run | 127.2 s | 300.9 s |
| Estimated API cost, three runs total | $0.0517 | $0.2578 |
| Median estimated API cost per run | $0.0149 | $0.0776 |
| Review responses cut off at the output limit | 0 | 6 |
| Residual infrastructure errors after retries | 0 | 0 |

| Puzzle | Exact: GLM / Nemotron | Tokens: GLM / Nemotron | Seconds: GLM / Nemotron |
|---|---|---|---|
| I'm Alright | 1/1 / 1/1 | 84,353 / 134,343 | 300.1 / 300.9 |
| FM (A Grid Charlemagne Puzzle) | 1/1 / 1/1 | 59,696 / 128,274 | 127.2 / 168.9 |
| Garden Party | 1/1 / 1/1 | 56,602 / 183,924 | 112.4 / 408.1 |

**Observed trade-off:** no accuracy gain on these three puzzles, with **2.25× median total tokens, 2.36× median latency and 4.98× estimated total cost** for Nemotron review. Its median review-request token count was 3.41× higher. Six Nemotron review responses used all 6,000 completion tokens as reasoning, returned empty content and triggered batch splitting; GLM review had no such cutoffs. Each cohort also needed five transient HTTP retry attempts, all recovered.

Costs use provider-reported input and output tokens, including reasoning, at the published uncached rates checked on October 26: GLM $0.15/$0.50 and Nemotron $0.30/$0.90 per million input/output tokens. These are list-price estimates for the six completed runs, not invoices; discounts, caching adjustments and the initial API smoke call are excluded. Sources: [Nebius GLM pricing](https://nebius.com/services/token-factory/models/glm-models-inference), [Nebius Nemotron pricing](https://nebius.com/blog/posts/three-new-open-weight-models-from-us-companies-give-builders-more-choice).

**Limits and interpretation.** Three selected development puzzles with one run each cannot establish a general accuracy difference or equivalence. All paired outcomes tied (exact McNemar p = 1); the all-zero bootstrap difference is degenerate because all observed solves succeeded. These are end-to-end configuration comparisons: the runs also differ in stochastic GLM fill/repair behavior, and the two-model configuration requires Nemotron to confirm GLM's joint-repair changes. In particular, the slower Garden Party run spent extra time in GLM fill/repair before Nemotron review. Thus, the total latency difference is not solely reviewer latency. The current settings were not tuned for Nemotron, and the historical memorization probe does not cover it.

Evidence: [protocol](protocol.json), [comparison JSON](comparison.json), [generated table](comparison.md). Raw runs and the execution log are in this folder.

To validate and summarize the saved runs without API calls, run from the repository root:

```bash
python results/benchmark/reviewer_public3_20261026/summarize_pilot.py
```

The pilot runner checks the frozen source and runner hashes. Current source changes prevent resuming these runs; a new live experiment requires a separate output folder.
