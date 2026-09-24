"""Bounded OpenAI-compatible client; no framework or extra HTTP dependency."""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path=".env"):
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class BudgetExceeded(RuntimeError):
    pass


class Client:
    def __init__(self, model=None, max_tokens=6000, max_calls=100, token_budget=180000):
        load_env()
        self.model = model or os.environ.get("NEBIUS_MODEL", "zai-org/GLM-5.3-Flash")
        self.key = os.environ.get("NEBIUS_API_KEY")
        if not self.key:
            raise ValueError("Set NEBIUS_API_KEY in .env or the environment.")
        if min(max_tokens, max_calls, token_budget) < 1:
            raise ValueError("Token and call budgets must be positive.")
        self.max_tokens, self.max_calls, self.token_budget = max_tokens, max_calls, token_budget
        self.calls, self.tokens, self.http_retries = 0, 0, 0
        self.lock = threading.Lock()

    def complete(self, messages, max_tokens=None):
        payload = {"model": self.model, "messages": messages, "temperature": 0.2,
                   "max_tokens": max_tokens or self.max_tokens}
        if self.model.startswith("zai-org/GLM-5.3"):
            payload["reasoning_effort"] = "low"
        started = time.monotonic()
        for attempt in range(3):
            with self.lock:
                if self.calls >= self.max_calls or self.tokens >= self.token_budget:
                    raise BudgetExceeded("Call or reported-token budget reached.")
                self.calls += 1
                self.http_retries += int(attempt > 0)
            request = urllib.request.Request(
                "https://api.tokenfactory.nebius.com/v1/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            delay = 2 ** attempt
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    data = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f"Token Factory HTTP {error.code}.") from None
                try:
                    delay = min(30, max(delay, float((error.headers or {}).get("Retry-After", delay))))
                except (TypeError, ValueError):
                    pass
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError("Token Factory request failed after three attempts.") from None
            time.sleep(delay)
        usage = data.get("usage", {})
        with self.lock:
            self.tokens += usage.get("total_tokens", 0)
        choice = data["choices"][0]
        return {"text": choice["message"].get("content") or "",
                "finish_reason": choice.get("finish_reason"), "usage": usage,
                "max_tokens": payload["max_tokens"], "http_attempts": attempt + 1,
                "latency_seconds": round(time.monotonic() - started, 3)}
