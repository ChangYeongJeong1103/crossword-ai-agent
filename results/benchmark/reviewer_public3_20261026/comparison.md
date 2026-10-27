# Public three-puzzle reviewer pilot

Selected public development puzzles; diagnostic pilot, not held-out evaluation.

GLM-5.3-Flash remains the default for all stages and the basis of the main evaluation. See [trial notes](README.md) for the protocol, limitations and interpretation.

Each reviewer: three puzzles, one fresh run each. Fill, repair and crosscheck use GLM.

| Metric | GLM review | Nemotron review |
|---|---:|---:|
| Exact solves | 3/3 (100.0%) | 3/3 (100.0%) |
| Clue accuracy | 100.00% | 100.00% |
| Cell accuracy | 100.00% | 100.00% |
| False accepts | 0 | 0 |
| Median review tokens | 27,806 | 94,957 |
| Median tokens | 59,696 | 134,343 |
| Median latency (s) | 127.2 | 300.9 |
| Total estimated USD | $0.0517 | $0.2578 |
| Median estimated USD/run | $0.0149 | $0.0776 |

| Puzzle | GLM exact / 1 | Nemotron exact / 1 |
|---|---:|---:|
| I'm Alright | 1 | 1 |
| FM (A Grid Charlemagne Puzzle) | 1 | 1 |
| Garden Party | 1 | 1 |

Paired exact-rate difference: +0.0 pp; 95% puzzle-cluster bootstrap CI [+0.0, +0.0] pp.
Exact per puzzle (one run): before-only 0, after-only 0; exact McNemar p=1.
The bootstrap interval is degenerate when all observed outcomes are identical; it does not establish equivalence or rule out rare failures.

Estimated uncached list price, including reported reasoning output tokens; excludes discounts. Only the six completed pilot runs are counted; the API smoke call is excluded.

Price sources: [Nebius GLM](https://nebius.com/services/token-factory/models/glm-models-inference), [Nebius Nemotron](https://nebius.com/blog/posts/three-new-open-weight-models-from-us-companies-give-builders-more-choice).
