"""Reported default configuration, shared by the client, solver, CLI and demo."""
MODEL = "zai-org/GLM-5.3-Flash"
MAX_ROUNDS = 15
BATCH_SIZE = 4
MAX_TOKENS = 6000
MAX_CALLS = 200  # HTTP attempts per puzzle, including transient retries.
TOKEN_BUDGET = 400000
