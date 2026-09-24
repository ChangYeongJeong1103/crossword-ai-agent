"""Small live/replay demo for the take-home assignment."""
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path

import streamlit as st

from src.evaluator import evaluate
from src.llm_client import Client, load_env
from src.puzzle import Puzzle
from src.solver import solve

ROOT = Path(__file__).parent
DATA = ROOT / "data/benchmark"
LIVE_RUNS = ROOT / "live_runs"
MAX_ROUNDS = 12
MAX_TOKENS = 6000
MAX_CALLS = 200
TOKEN_BUDGET = 400000


def source_sha256():
    """Return the hash used to identify one solver implementation."""
    source_files = sorted((ROOT / "src").rglob("*.py"))
    return hashlib.sha256(
        b"".join(path.read_bytes() for path in source_files)
    ).hexdigest()


def save_live_run(result):
    """Save one completed live run without replacing recorded results."""
    timestamp = datetime.now(timezone.utc)
    run_id = result.setdefault(
        "run_id", timestamp.strftime("%Y%m%dT%H%M%S_%fZ")
    )
    result.setdefault("created_at", timestamp.isoformat())
    result.setdefault("config", {
        "max_rounds": MAX_ROUNDS,
        "max_tokens": MAX_TOKENS,
        "max_calls": MAX_CALLS,
        "token_budget": TOKEN_BUDGET,
    })
    result.setdefault("source_sha256", source_sha256())

    LIVE_RUNS.mkdir(parents=True, exist_ok=True)
    destination = LIVE_RUNS / f"{run_id}_{result['puzzle_id']}.json"
    destination.write_text(json.dumps(result, indent=2) + "\n")
    return destination


def round_summary(record):
    """Build compact diagnostics from one solver round."""
    responses = record.get("responses", [])
    return {
        "round": record["round"],
        "phase": record.get("phase", "solve"),
        "answered": record["answered"],
        "reviewed": record.get("reviewed", 0),
        "calls": record.get("calls", 0),
        "tokens": sum(
            response.get("usage", {}).get("total_tokens", 0)
            for response in responses
        ),
        "empty": sum(
            not response.get("text", "").strip()
            and not response.get("budget_exhausted")
            for response in responses
        ),
        "retries": sum(
            max(0, response.get("http_attempts", 1) - 1)
            for response in responses
        ),
        "rejected": sum(
            len(response.get("rejected", {}))
            for response in responses
        ),
        "errors": sum(
            bool(response.get("error")) for response in responses
        ),
        "latency_seconds": record["latency_seconds"],
    }


def board(puzzle, answers):
    """Render the crossword grid as a small HTML table."""
    numbers = {
        tuple(clue["start"]): clue["id"][:-1]
        for clue in puzzle.clues.values()
    }
    rows = []
    for row_index, row in enumerate(puzzle.render(answers)):
        cells = []
        for col_index, letter in enumerate(row):
            if letter == "#":
                cells.append('<td style="background:#202b3a"></td>')
            else:
                number = html.escape(
                    numbers.get((row_index, col_index), "")
                )
                displayed = letter if letter != "." else ""
                cells.append(
                    f"<td><small>{number}</small>{displayed}</td>"
                )
        rows.append("<tr>" + "".join(cells) + "</tr>")

    st.html(
        '<style>.crossword{border-collapse:collapse;background:white;color:#111}'
        '.crossword td{border:1px solid #aab3be;width:28px;height:28px;'
        'text-align:center;position:relative;font:18px monospace;padding:3px}'
        '.crossword small{position:absolute;top:0;left:2px;'
        'font:8px sans-serif}</style>'
        '<table class="crossword">' + "".join(rows) + "</table>"
    )


def main():
    """Run the Streamlit live/replay interface."""
    st.set_page_config(page_title="Crossword Agent", layout="wide")
    st.title("Crossword Agent")
    st.caption("Solve clues → check crossings → retry with letters → review meaning")

    paths = sorted(
        DATA.glob("*/puzzles/*.json"),
        key=lambda path: ("im_alright" not in path.stem, path.name),
    )
    path = st.selectbox(
        "15×15 puzzle",
        paths,
        format_func=lambda item: item.stem.replace("crossword_nexus_", ""),
    )
    puzzle = Puzzle.load(path)
    evaluation_set = path.parent.parent.name == "held_out"
    st.caption("Evaluation set" if evaluation_set else "Development set")

    load_env(ROOT / ".env")
    model = st.text_input(
        "Model",
        os.environ.get("NEBIUS_MODEL", "zai-org/GLM-5.3-Flash"),
    )
    st.caption(
        "**Solve live** makes real API calls, uses credits, and can range from "
        "under a minute to over 30 minutes. Progress updates after each round. "
        "**Show recorded run** is instant and makes no API calls."
    )

    live_column, replay_column = st.columns(2)
    result_folder = ROOT / "results"
    if evaluation_set:
        result_folder = result_folder / "held_out"
    saved = result_folder / f"{puzzle.id}.json"
    live_clicked = live_column.button(
        "Solve live",
        type="primary",
        help="Run the agent with live Nebius API calls.",
    )
    replay_clicked = replay_column.button(
        "Show recorded run",
        disabled=not saved.exists(),
        help="Load the saved result without making an API call.",
    )
    status = st.empty()

    if live_clicked:
        status.info(
            "Starting live solve. The first progress update appears after "
            "round 1 finishes and may take several minutes."
        )

        def update_progress(record):
            status.info(
                f"Solving live · completed round {record['round']}/{MAX_ROUNDS} · "
                f"{record['answered']}/{len(puzzle.clues)} answers · "
                f"{record['conflicts']} conflicts"
            )

        try:
            result = solve(
                puzzle,
                Client(
                    model,
                    max_tokens=MAX_TOKENS,
                    max_calls=MAX_CALLS,
                    token_budget=TOKEN_BUDGET,
                ),
                max_rounds=MAX_ROUNDS,
                progress=update_progress,
            )
            gold_path = path.parent.parent / "gold" / path.name
            result["evaluation"] = evaluate(
                puzzle, result["answers"], gold_path
            )
            st.session_state["result"] = result
            st.session_state["mode"] = "Live run"

            if result["evaluation"]["exact_solve"]:
                status.success(
                    f"Exact solve in {len(result['trace'])} rounds. "
                    f"Controller termination: `{result['termination']}`."
                )
            elif result["termination"] == "complete_consistent_grid":
                status.warning(
                    "The controller completed its internal review, but the "
                    "gold evaluation found an incorrect answer."
                )
            else:
                status.warning(
                    f"Live run stopped with `{result['termination']}`. "
                    "The best consistent partial result is shown below."
                )
        except (ValueError, RuntimeError, OSError) as error:
            status.error(f"Live solve failed: {error}")

    if replay_clicked:
        st.session_state["result"] = json.loads(saved.read_text())
        st.session_state["mode"] = "Recorded run (not a new API call)"
        status.success("Recorded run loaded. No API call or credits were used.")

    result = st.session_state.get("result", {})
    if result.get("puzzle_id") != puzzle.id:
        board(puzzle, {})
        return

    live_run_path = None
    if st.session_state.get("mode") == "Live run":
        try:
            live_run_path = save_live_run(result)
            st.session_state["live_run_path"] = str(live_run_path)
        except OSError as error:
            status.warning(f"Live result could not be saved: {error}")

    st.caption(
        f"{st.session_state['mode']} · "
        f"{result['model']} · {result['termination']}"
    )
    left, right = st.columns([1, 1])
    with left:
        board(puzzle, result["answers"])
    with right:
        metrics = result.get("evaluation", {})
        st.metric(
            "Clue accuracy", f"{metrics.get('clue_accuracy', 0):.1%}"
        )
        st.metric(
            "Cell accuracy", f"{metrics.get('cell_accuracy', 0):.1%}"
        )
        st.write(
            f"{result['calls']} calls · {result['tokens']:,} tokens · "
            f"{result['latency_seconds']:.1f}s"
        )
        st.write(
            "Exact solve:", metrics.get("exact_solve", "Not evaluated")
        )
        if live_run_path:
            relative_path = live_run_path.relative_to(ROOT)
            st.caption(f"Automatically saved to `{relative_path}`")
        st.download_button(
            "Download run JSON",
            data=json.dumps(result, indent=2) + "\n",
            file_name=(
                live_run_path.name
                if live_run_path
                else f"{puzzle.id}_recorded.json"
            ),
            mime="application/json",
        )

    with st.expander("Agent rounds"):
        st.dataframe(
            [round_summary(record) for record in result["trace"]],
            hide_index=True,
        )
        for record in result["trace"]:
            st.write(
                f"Round {record['round']} corrections",
                record["changes"],
            )


if __name__ == "__main__":
    main()
