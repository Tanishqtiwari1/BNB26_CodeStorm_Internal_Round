"""LLM client for the real reference agent.

Provider selection (env BLACKBOX_LLM):
  auto (default)  -> Anthropic if ANTHROPIC_API_KEY is set, otherwise mock
  anthropic       -> always call the Anthropic API
  mock            -> deterministic offline stand-in (no network)

Responses are cached in SQLite keyed by (provider, model, system, prompt) so
replays and demos are reproducible and don't re-bill identical calls.
"""
import hashlib
import json
import os
import re
import sqlite3
import threading

MODEL = os.environ.get("BLACKBOX_LLM_MODEL", "claude-opus-5-5")
_lock = threading.Lock()


def provider():
    p = os.environ.get("BLACKBOX_LLM", "auto").lower()
    if p == "auto":
        return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "mock"
    return p


def describe():
    p = provider()
    return {"provider": p, "model": MODEL if p == "anthropic" else "mock-llm (deterministic)"}


class LLMError(RuntimeError):
    pass


class _Cache:
    def __init__(self, path=os.environ.get("BLACKBOX_LLM_CACHE", "data/llm_cache.db")):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT)")

    def get(self, k):
        with _lock:
            row = self.db.execute("SELECT v FROM cache WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def put(self, k, v):
        with _lock:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?)", (k, v))
            self.db.commit()


_cache = None
_client = None


def complete(system, prompt, mock_fn, max_tokens=1024, use_cache=True):
    """Return the model's text. `mock_fn(prompt)` produces the offline answer."""
    global _cache, _client
    p = provider()
    if p == "mock":
        return mock_fn(prompt)
    _cache = _cache or _Cache()
    key = hashlib.sha256(json.dumps([p, MODEL, system, prompt]).encode()).hexdigest()
    if use_cache and (hit := _cache.get(key)) is not None:
        return hit
    import anthropic
    _client = _client or anthropic.Anthropic()
    try:
        resp = _client.beta.messages.create(
            model=MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
    except anthropic.APIConnectionError as e:
        raise LLMError(f"network error: {e}") from e
    except anthropic.RateLimitError as e:
        raise LLMError("rate limited") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"API error {e.status_code}: {e.message}") from e
    if resp.stop_reason == "refusal":
        raise LLMError("model refused the request")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    _cache.put(key, text)
    return text


def parse_json(text):
    """Extract the first JSON object from a model response."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise LLMError(f"no JSON object in model output: {text[:120]!r}")
    return json.loads(m.group(0))
