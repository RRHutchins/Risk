"""Stage 8: test and tune.

Records, for every pack in a test run, the measures in the build brief
(section 13), checks them against the targets in config/settings.yaml, and
compares each pack with its previous run so the effect of a prompt change is
visible. The results file is a CSV that opens in Excel.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from risk_engine.config import resolve_path
from risk_engine.packs import load_pack

RESULT_FIELDS = [
    "time_utc", "label", "pack", "pack_type", "prompt_version", "documents", "pieces", "pieces_not_reviewed",
    "records", "excluded", "quotes_verified_share", "checklist_answered", "checklist_items",
    "checklist_all_reported", "figures_removed", "red", "P50_pct", "P80_pct", "indicator", "total_usd",
    "seconds", "target_quotes", "target_checklist", "target_numbers", "target_cost", "all_targets_met",
    "problem", "report",
]


def prompt_version(pack_name: str) -> str:
    """A short fingerprint of everything in the pack that steers Claude, so
    results can be grouped by prompt version."""
    pack = load_pack(pack_name)
    h = hashlib.sha256()
    for path in sorted(pack.folder.iterdir()):
        if path.is_file():
            h.update(path.name.encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:8]


def evaluate(row: dict, targets: dict) -> dict:
    """PASS / FAIL against the brief's targets for one pack."""
    def flag(ok):
        return "PASS" if ok else "FAIL"

    if row.get("problem"):
        out = {k: "n/a" for k in ("target_quotes", "target_checklist", "target_numbers", "target_cost")}
        out["all_targets_met"] = "FAIL"
        return out
    share = float(row.get("quotes_verified_share") or 0)
    records_and_excluded = int(row.get("records") or 0) + int(row.get("excluded") or 0)
    out = {
        "target_quotes": "n/a" if records_and_excluded == 0 else flag(share >= targets.get("quotes_verified_share_min", 0.98)),
        "target_checklist": flag(str(row.get("checklist_all_reported")) == "True"),
        "target_numbers": flag(int(row.get("figures_removed") or 0) == 0),
        "target_cost": flag(float(row.get("total_usd") or 0) <= targets.get("cost_per_pack_max_usd", 2.0)),
    }
    out["all_targets_met"] = "PASS" if all(v in ("PASS", "n/a") for v in out.values()) else "FAIL"
    return out


def record_results(summary_csv: Path, settings: dict, label: str) -> tuple[list[dict], Path]:
    """Append a batch summary to the test results file, with targets checked."""
    cfg = settings.get("testing", {})
    targets = cfg.get("targets", {})
    results = results_file(settings)
    rows = list(csv.DictReader(open(summary_csv, newline="", encoding="utf-8")))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    out = []
    for r in rows:
        row = {k: r.get(k, "") for k in RESULT_FIELDS}
        row.update({"time_utc": now, "label": label})
        if r.get("pack_type"):
            row["prompt_version"] = prompt_version(r["pack_type"])
        row.update(evaluate(r, targets))
        out.append(row)
    results.parent.mkdir(parents=True, exist_ok=True)
    new = not results.exists()
    with open(results, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        if new:
            w.writeheader()
        w.writerows(out)
    return out, results


def previous_results(results: Path) -> dict[str, dict]:
    """The most recent result for each pack name already in the file."""
    if not results.exists():
        return {}
    latest: dict[str, dict] = {}
    for r in csv.DictReader(open(results, newline="", encoding="utf-8")):
        latest[r["pack"]] = r
    return latest


def results_file(settings: dict) -> Path:
    return resolve_path(settings.get("testing", {}).get("results_file", "ledger/test_results.csv"))


def compare(rows: list[dict], previous: dict[str, dict]) -> list[str]:
    """Plain-English differences from each pack's previous run."""
    lines = []
    for r in rows:
        old = previous.get(r["pack"])
        if not old:
            lines.append(f"{r['pack']}: first run")
            continue
        changes = []
        for key, label in (("records", "records"), ("quotes_verified_share", "quotes verified"),
                           ("checklist_answered", "checklist answered"), ("red", "red risks"),
                           ("P80_pct", "P80 %"), ("total_usd", "cost $"), ("indicator", "indicator")):
            if str(old.get(key, "")) != str(r.get(key, "")):
                changes.append(f"{label} {old.get(key, '') or '-'} -> {r.get(key, '') or '-'}")
        if old.get("prompt_version") != r.get("prompt_version"):
            changes.insert(0, f"prompt version {old.get('prompt_version')} -> {r.get('prompt_version')}")
        lines.append(f"{r['pack']}: " + ("; ".join(changes) if changes else "no change"))
    return lines
