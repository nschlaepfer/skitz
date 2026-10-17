"""A daily Suno credit budget, so an agent can generate inside it without asking each time.

The limit comes from SKITZ_SUNO_BUDGET (credits per day) or `skitz suno budget set N`
(~/.skitz/suno/budget.json); the environment wins. Every generation is recorded in
~/.skitz/suno/spend.jsonl with the credits before and after, and a generation that would
pass today's limit is refused before anything is sent. Days are local calendar days.
"""

import json
import os
import time
from pathlib import Path

from .suno_inbox import suno_home

# What a generation (2 clips) is assumed to cost before Skitz has seen a real one.
DEFAULT_COST = float(os.environ.get("SKITZ_SUNO_COST", "10"))


def budget_file() -> Path:
    return suno_home() / "budget.json"


def spend_file() -> Path:
    return suno_home() / "spend.jsonl"


def today() -> str:
    return time.strftime("%Y-%m-%d")


def daily_limit() -> tuple[float | None, str | None]:
    """The daily limit in credits and where it came from ("env", "file"), or (None, None)."""
    configured = os.environ.get("SKITZ_SUNO_BUDGET", "").strip()
    if configured:
        try:
            return max(0.0, float(configured)), "env"
        except ValueError:
            raise ValueError(f"SKITZ_SUNO_BUDGET must be a number of credits, not {configured!r}")
    path = budget_file()
    try:
        value = json.loads(path.read_text()).get("daily_credits") if path.is_file() else None
    except ValueError:
        value = None
    return (float(value), "file") if isinstance(value, int | float) else (None, None)


def set_limit(credits: float | None) -> Path:
    """Save the daily limit; None removes it."""
    path = budget_file()
    if credits is None:
        path.unlink(missing_ok=True)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"daily_credits": credits}, indent=2))
    return path


def entries() -> list[dict]:
    path = spend_file()
    if not path.is_file():
        return []
    found = []
    for line in path.read_text().splitlines():
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found


def spent_today() -> float:
    day = today()
    return sum(float(e.get("spent") or 0) for e in entries() if e.get("day") == day)


def next_cost(model: str | None = None) -> float:
    """The last measured cost of a generation (same model first), else DEFAULT_COST."""
    measured = [e for e in entries() if not e.get("estimated") and (e.get("spent") or 0) > 0]
    same = [e for e in measured if e.get("model") == model]
    latest = (same or measured or [None])[-1]
    return float(latest["spent"]) if latest else DEFAULT_COST


def status(model: str | None = None) -> dict:
    limit, source = daily_limit()
    spent = spent_today()
    cost = next_cost(model)
    return {
        "daily_limit": limit,
        "source": source,
        "day": today(),
        "spent_today": spent,
        "remaining": None if limit is None else max(0.0, limit - spent),
        "next_cost": cost,
        "allowed": limit is None or spent + cost <= limit,
    }


def record(ids: list[str], model: str | None, before: float | None, after: float | None) -> dict:
    """Append one generation to the spend ledger.

    The cost is credits before minus after. When that can't be measured (billing failed,
    or Suno hadn't deducted yet) the expected cost is recorded and marked `estimated`, so
    the budget errs on the side of spending less.
    """
    measured = before - after if before is not None and after is not None else None
    estimated = measured is None or measured <= 0
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "day": today(),
        "ids": ids,
        "model": model,
        "credits_before": before,
        "credits_after": after,
        "spent": next_cost(model) if estimated else measured,
        "estimated": estimated,
    }
    path = spend_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry
