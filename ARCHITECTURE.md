# How the AI Agent Solves a Crossword

The model proposes answers. Python controls the solve, checks every proposal and decides what the model should reconsider.

## Complete solving flow

```mermaid
flowchart TD
  A["1. Load blank grid and clues"] --> B["2. Build answer slots,<br/>crossings and letter patterns"]
  B --> C{"3. Choose the next phase"}

  C -->|"Missing answers<br/>and still progressing"| D["FILL<br/>Ask for missing answers"]
  C -->|"Stalled or blocked"| E["REPAIR<br/>Reconsider difficult entries<br/>with crossing clues"]
  C -->|"Grid is full"| F["REVIEW<br/>Check every answer<br/>against its clue"]

  D --> G["4. Build model context<br/>clue + length + pattern<br/>theme + cross-references"]
  E --> G
  F --> G

  G --> H["5. Send batches of 4 clues<br/>Up to 4 calls in parallel"]
  H --> I["6. GLM returns JSON answers"]
  I --> J["7. Validate each proposal<br/>normalize spaces, apostrophes and hyphens<br/>A-Z · exact length · fill-pattern match"]

  J -->|"Missing ID or<br/>unparseable JSON"| K["Retry only failed clue IDs<br/>Empty length-limited batch → single clues<br/>Larger retry only for original singleton"]
  K --> I

  J -->|"Invalid length, characters<br/>or fill pattern"| T["Reject proposal<br/>Reconsider in a later round"]
  T -.-> C
  J -->|"Valid proposals"| L["8. Merge answers and<br/>detect crossing conflicts"]
  L --> M["9. Remove conflicting answers<br/>Keep consistent regions<br/>Prefer semantic corrections"]

  M --> N{"10. Complete and<br/>semantically reviewed?"}
  N -->|"No"| O{"Round, call or<br/>token budget left?"}
  O -->|"Yes"| C
  O -->|"No"| P["Return the best<br/>consistent partial grid"]
  N -->|"Yes"| Q["Return completed grid<br/>and full solve trace"]

  P --> R["11. Optional evaluator<br/>opens separate gold file"]
  Q --> R
  R --> S["Exact solve · clue accuracy<br/>cell accuracy"]

  classDef input fill:#e8f1ff,stroke:#2563eb,color:#0f172a;
  classDef phase fill:#fff4d6,stroke:#d97706,color:#0f172a;
  classDef model fill:#f3e8ff,stroke:#9333ea,color:#0f172a;
  classDef check fill:#e8fff3,stroke:#059669,color:#0f172a;
  classDef decision fill:#fff7ed,stroke:#ea580c,color:#0f172a;
  classDef result fill:#e0f2fe,stroke:#0284c7,color:#0f172a;

  class A,B input;
  class D,E,F phase;
  class G,H,I,K model;
  class J,L,M,R,T check;
  class C,N,O decision;
  class P,Q,S result;
```

## What happens inside each phase

```mermaid
flowchart LR
  FILL["FILL<br/>Use known crossing letters<br/>as hard pattern constraints"]
  REPAIR["REPAIR<br/>Treat current letters as tentative<br/>and inspect nearby crossings"]
  REVIEW["REVIEW<br/>Check clue meaning even when<br/>all letters already fit"]

  FILL -->|"No progress or<br/>fully blocked pattern"| REPAIR
  FILL -->|"Grid becomes complete"| REVIEW
  REPAIR -->|"Grid becomes complete"| REVIEW
  REPAIR -->|"Progress with<br/>gaps remaining"| FILL
  REPAIR -->|"No progress"| REPAIR
  REVIEW -->|"Correction creates<br/>a crossing conflict"| JOINT["JOINT RECHECK<br/>Check the correction with<br/>its conflicting crossing"]
  JOINT -->|"All answers confirmed"| DONE["DONE"]
  JOINT -->|"Grid remains full<br/>but review is pending"| REVIEW
  JOINT -->|"Pruning removes<br/>an answer"| FILL
  REVIEW -->|"Some answers not<br/>yet confirmed"| REVIEW
  REVIEW -->|"All answers confirmed"| DONE

  classDef phase fill:#fff4d6,stroke:#d97706,color:#0f172a;
  classDef done fill:#dcfce7,stroke:#16a34a,color:#0f172a;
  class FILL,REPAIR,REVIEW,JOINT phase;
  class DONE done;
```

### Fill

- Requests only unanswered clues.
- Uses existing crossing letters as required pattern letters.
- Rejects wrong lengths, invalid characters and pattern violations.

### Repair

- Activates when progress stops or a fully determined pattern is rejected.
- Sends difficult missing entries together with their crossing clues.
- Treats existing letters as tentative so an earlier wrong answer can be replaced.
- Jointly rechecks a semantic correction and any answer that conflicts with it.
- Returns to fill after making progress with gaps remaining; stays in repair after no progress.

### Review

- Runs after the grid has an answer for every clue.
- Asks the model to confirm clue meaning instead of trusting crossings alone.
- Prevents a rejected answer from immediately returning through fill mode.
- Immediately rechecks a semantic correction with any conflicting crossing answer.
- If pruning removes an answer, the next round fills the resulting gap.

### Retry and budget control

- Immediately retries missing IDs and responses that cannot be parsed.
- Rejects invalid characters, lengths and fill-pattern violations; the next round can reconsider those clues.
- Retries an empty length-limited batch directly as individual clues instead of recursively creating intermediate batches.
- Does not give a split-generated singleton another 12,000-token attempt.
- Preserves one larger retry for a request that started as a singleton.
- Records each returned response, final error and provider usage report in the solve trace.
- Summarizes transient HTTP retries with `http_attempts` rather than storing each intermediate HTTP error.

## Prompt context sent to the model

```mermaid
flowchart LR
  A["Requested clue"] --> P["Model prompt"]
  B["Required length"] --> P
  C["Current letter pattern"] --> P
  D["Crossing clues and answers<br/>during repair/review"] --> P
  E["Referenced clues<br/>such as See 12-Down"] --> P
  F["Other long clues and answers<br/>when a requested clue has 10+ letters"] --> P
  P --> G["JSON answers only"]
```

The model never receives the gold solution. Gold remains outside the solving loop and is opened only after `solve()` returns.

## Gold boundary

```mermaid
flowchart LR
  P["Puzzle grid + clues"] --> S["Solver"]
  S <-->|"Prompt context<br/>and JSON proposals"| M["GLM-5.3-Flash"]
  S --> A["Returned answers + trace"]
  A --> E["Evaluator"]
  G["Separate gold file"] --> E
  E --> R["Measured scores"]

  classDef protected fill:#fee2e2,stroke:#dc2626,color:#0f172a;
  class G protected;
```

## Code responsibilities

| Component | File | Responsibility |
|---|---|---|
| Puzzle | `src/puzzle.py` | Load and validate the grid; build slots, patterns and crossings |
| Model client | `src/llm_client.py` | Call Nebius Token Factory; enforce call/token budgets and HTTP retries |
| Solver | `src/solver.py` | Run fill, repair, review, validation, pruning and tracing |
| Evaluator | `src/evaluator.py` | Compare returned answers with gold after inference |
| Demo | `app.py` | Show live solving or replay a recorded run |
| CLI | `run_eval.py` | Run one puzzle, optionally evaluate it and save the full result |

The reported app and CLI configuration uses 12 rounds, up to 200 HTTP attempts and a 400,000 reported-token threshold per puzzle. The round limit is configurable up to 30, and concurrent in-flight requests can take reported usage slightly above the token threshold. The controller uses no answer retrieval, candidate beam or constraint-satisfaction solver. A structurally complete grid can still be semantically wrong, so only the separate evaluator can establish an exact solve.
