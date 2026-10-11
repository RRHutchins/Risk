"""Cost controls: token counting, run estimates, the spending cap and the ledger.

All money figures here are calculated by code from the prices in
config/settings.yaml. Nothing is guessed by the language model.
"""

from __future__ import annotations

import csv
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MILLION = 1_000_000


class SpendCapExceeded(Exception):
    """Raised to stop a run that would go over the per-run spending cap."""


# ---------------------------------------------------------------------------
# Token counting (local, no API call)
# ---------------------------------------------------------------------------

def count_tokens_local(text: str, chars_per_token: float) -> int:
    """Approximate token count without calling the API.

    Deliberately on the high side: English averages about 4 characters per
    token, and the default setting of 3.5 over-counts slightly.
    """
    if not text:
        return 0
    return math.ceil(len(text) / chars_per_token)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

@dataclass
class Usage:
    """Tokens used by one API call (or a planned call)."""
    input: int = 0          # ordinary input tokens
    cache_write: int = 0    # input tokens written to the prompt cache
    cache_read: int = 0     # input tokens read from the prompt cache
    output: int = 0


def price_usage(model: str, usage: Usage, pricing: dict, batch: bool = False) -> float:
    """Cost in US dollars of the given token usage on the given model."""
    if model not in pricing:
        raise KeyError(f"No price listed for model '{model}' in config/settings.yaml (pricing section).")
    p = pricing[model]
    cache_write_price = p["input"] * pricing.get("cache_write_multiplier", 1.25)
    cache_read_price = p.get("cache_read", p["input"] * 0.1)
    cost = (
        usage.input * p["input"]
        + usage.cache_write * cache_write_price
        + usage.cache_read * cache_read_price
        + usage.output * p["output"]
    ) / MILLION
    if batch:
        cost *= pricing.get("batch_discount", 0.5)
    return cost


# ---------------------------------------------------------------------------
# Run estimate
# ---------------------------------------------------------------------------

@dataclass
class EstimateLine:
    step: str
    model: str
    calls: int
    usage: Usage
    cost_usd: float


@dataclass
class Estimate:
    lines: list[EstimateLine] = field(default_factory=list)
    safety_margin: float = 0.0
    batch: bool = False

    @property
    def subtotal_usd(self) -> float:
        return sum(line.cost_usd for line in self.lines)

    @property
    def total_usd(self) -> float:
        return self.subtotal_usd * (1 + self.safety_margin)


def estimate_run(chunk_tokens: list[int], pack_context_tokens: int, synth_prompt_tokens: int,
                 settings: dict, batch: bool = False) -> Estimate:
    """Estimate the cost of a full run before it starts.

    chunk_tokens         tokens in each chunk of document text
    pack_context_tokens  tokens in the pack instructions sent with every
                         extraction call (cached after the first call)
    synth_prompt_tokens  tokens in the synthesis instructions
    """
    est_cfg = settings["estimate"]
    pricing = settings["pricing"]
    models = settings["models"]
    n = len(chunk_tokens)
    est = Estimate(safety_margin=est_cfg.get("safety_margin", 0.0), batch=batch)

    def add(step: str, model: str, calls: int, usage: Usage):
        est.lines.append(EstimateLine(step, model, calls, usage,
                                      price_usage(model, usage, pricing, batch=batch)))

    if n == 0:
        return est

    # 1. Extraction: pack instructions are written to the cache once, then
    #    read from the cache on every later call.
    add("Extraction", models["extraction"], n, Usage(
        input=sum(chunk_tokens),
        cache_write=pack_context_tokens,
        cache_read=pack_context_tokens * (n - 1),
        output=est_cfg["extraction_output_tokens_per_chunk"] * n,
    ))

    # 2. Classification and duplicate merging.
    records = est_cfg["records_per_chunk"] * n
    add("Classification", models["classification"], 1, Usage(
        input=records * est_cfg["classification_input_tokens_per_record"],
        output=records * est_cfg["classification_output_tokens_per_record"],
    ))

    # 3. Synthesis: one call with the register and the calculated numbers.
    add("Synthesis", models["synthesis"], 1, Usage(
        input=est_cfg["synthesis_input_tokens"] + synth_prompt_tokens,
        output=est_cfg["synthesis_output_tokens"],
    ))
    return est


# ---------------------------------------------------------------------------
# Spending cap (used from Stage 3, when real API calls begin)
# ---------------------------------------------------------------------------

class CostGuard:
    """Keeps a running total for one run and stops it at the cap.

    Before each API call, reserve() its expected cost: if the money already
    spent plus every call still in progress plus this one could pass the cap,
    the call is refused before anything is spent. After the call, record() the
    real token usage, which releases the reservation. Safe to use from several
    threads at once.
    """

    def __init__(self, cap_usd: float, pricing: dict):
        self.cap_usd = cap_usd
        self.pricing = pricing
        self.spent_usd = 0.0
        self.reserved_usd = 0.0
        self._lock = threading.Lock()

    def reserve(self, expected_cost_usd: float) -> None:
        with self._lock:
            committed = self.spent_usd + self.reserved_usd
            if committed + expected_cost_usd > self.cap_usd:
                raise SpendCapExceeded(
                    f"Stopping: this run has spent ${self.spent_usd:.4f} (plus ${self.reserved_usd:.4f} "
                    f"for calls in progress) and the next call could cost about ${expected_cost_usd:.4f}, "
                    f"which would pass the per-run cap of ${self.cap_usd:.2f} (set in "
                    f"config/settings.yaml, budget: per_run_cap_usd)."
                )
            self.reserved_usd += expected_cost_usd

    def release(self, expected_cost_usd: float) -> None:
        """Cancel a reservation for a call that was not made or failed."""
        with self._lock:
            self.reserved_usd = max(0.0, self.reserved_usd - expected_cost_usd)

    def record(self, model: str, usage: Usage, reserved_usd: float = 0.0, batch: bool = False) -> float:
        """Record what a call really cost. Returns the cost in US dollars."""
        cost = price_usage(model, usage, self.pricing, batch=batch)
        with self._lock:
            self.reserved_usd = max(0.0, self.reserved_usd - reserved_usd)
            self.spent_usd += cost
        return cost

    def check_before(self, expected_cost_usd: float) -> None:
        """Raise if a call of this cost could pass the cap (without reserving)."""
        self.reserve(expected_cost_usd)
        self.release(expected_cost_usd)


# ---------------------------------------------------------------------------
# Ledger: a CSV file recording every run and every dollar spent
# ---------------------------------------------------------------------------

# Internal names (used by the code) and the column headings written to the file.
LEDGER_FIELDS = [
    "time_utc", "run_id", "mode", "step", "model",
    "input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens",
    "estimated_usd", "actual_usd", "note",
]
LEDGER_HEADINGS = [
    "Time (UTC)", "Run ID", "Mode", "Step", "Model",
    "Input tokens", "Cache write tokens", "Cache read tokens", "Output tokens",
    "Estimated cost (USD)", "Actual cost (USD)", "Note",
]


class Ledger:
    """A CSV file (opens in Excel) with one line per step of every run.

    Times are recorded in UTC so the file reads the same on any computer.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def _upgrade_headings(self) -> None:
        """Ledgers from Stage 1 used technical column names; rename them."""
        if not self.path.exists():
            return
        with open(self.path, newline="", encoding="utf-8") as f:
            lines = list(csv.reader(f))
        if lines and lines[0] != LEDGER_HEADINGS and len(lines[0]) == len(LEDGER_HEADINGS):
            lines[0] = LEDGER_HEADINGS
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(lines)

    def append(self, run_id: str, mode: str, step: str, model: str = "", usage: Usage | None = None,
               estimated_usd: float = 0.0, actual_usd: float = 0.0, note: str = "") -> None:
        usage = usage or Usage()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._upgrade_headings()
        new_file = not self.path.exists()
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(LEDGER_HEADINGS)
            writer.writerow([
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), run_id, mode, step, model,
                usage.input, usage.cache_write, usage.cache_read, usage.output,
                f"{estimated_usd:.6f}", f"{actual_usd:.6f}", note,
            ])

    def rows(self) -> list[dict]:
        """All entries, keyed by the internal field names."""
        if not self.path.exists():
            return []
        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # headings
            return [dict(zip(LEDGER_FIELDS, line)) for line in reader if line]

    def total_spent_usd(self) -> float:
        return sum(float(r["actual_usd"] or 0) for r in self.rows())

    def run_count(self) -> int:
        return len({r["run_id"] for r in self.rows()})
