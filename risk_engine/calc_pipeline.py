"""Stage 4 run: take the records from an extraction run, apply any edits made
in records.xlsx, merge duplicates, score, and simulate contingency."""

from __future__ import annotations

import json
import platform
import re
from datetime import datetime, timezone
from pathlib import Path

from risk_engine import __version__
from risk_engine.calculate import SimulationSettings, calculate
from risk_engine.classify import merge_duplicates, no_merge
from risk_engine.extract import ExtractionStopped
from risk_engine.config import ConfigError, resolve_path
from risk_engine.costs import CostGuard, Ledger
from risk_engine.packs import load_pack
from risk_engine.runs import create_run_folder

EDITABLE = {  # column heading in records.xlsx -> record field
    "Likelihood (1-5)": "likelihood",
    "Impact min %": "impact_min",
    "Impact likely %": "impact_likely",
    "Impact max %": "impact_max",
    "Correlation group": "correlation_group",
}


class CalculationError(Exception):
    """A plain-English problem with the inputs to a calculation."""


def parse_money(text: str | float | int | None) -> float | None:
    """'2,500,000', '£2.5m', '750k' -> a number. None stays None."""
    if text is None or text == "":
        return None
    if isinstance(text, (int, float)):
        return float(text)
    t = str(text).strip().lower().replace(",", "").replace("£", "").replace("$", "").replace("gbp", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|million|k|thousand|bn|billion)?", t)
    if not m:
        raise CalculationError(f"'{text}' is not a contract value I can read. Try a number such as 2500000 or 2.5m.")
    factor = {"m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3, "bn": 1e9, "billion": 1e9}.get(m.group(2), 1)
    return float(m.group(1)) * factor


def load_extraction(run_folder: Path) -> dict:
    audit = Path(run_folder) / "extraction_audit.json"
    if not audit.exists():
        raise CalculationError(f"No extraction results in {run_folder}. Give the folder that the 'extract' "
                               "command created inside 'outputs'.")
    return json.loads(audit.read_text(encoding="utf-8"))


def apply_excel_edits(records: list[dict], workbook: Path, pack_config: dict) -> tuple[list[dict], list[dict]]:
    """Use any changes made to likelihood, impact or correlation group in the
    'Risk records' sheet. Records deleted from the sheet are left out."""
    if not workbook.exists():
        return records, []
    import openpyxl

    ws = openpyxl.load_workbook(workbook, data_only=True)["Risk records"]
    rows = list(ws.iter_rows(values_only=True))
    try:
        header_row = next(i for i, r in enumerate(rows) if r and r[0] == "ID")
    except StopIteration:
        raise CalculationError("records.xlsx has no 'ID' column heading in the 'Risk records' sheet.")
    headings = list(rows[header_row])
    sheet = {}
    for n, row in enumerate(rows[header_row + 1:], start=header_row + 2):
        if row and row[0]:
            sheet[str(row[0]).strip()] = (n, dict(zip(headings, row)))

    scores = [s["score"] for s in pack_config["likelihood_scale"]]
    changes, kept = [], []
    for r in records:
        if r["id"] not in sheet:
            changes.append({"id": r["id"], "field": "(whole record)", "was": "present", "now": "deleted in Excel"})
            continue
        row_no, row = sheet[r["id"]]
        new = dict(r)
        for heading, field in EDITABLE.items():
            if heading not in row:
                continue
            value = row[heading]
            if field == "correlation_group":
                value = "" if value is None else str(value).strip()
            else:
                try:
                    value = int(value) if field == "likelihood" else float(value)
                except (TypeError, ValueError):
                    raise CalculationError(f"records.xlsx row {row_no} ({r['id']}): '{heading}' must be a number.")
            if value != r.get(field):
                changes.append({"id": r["id"], "field": field, "was": r.get(field), "now": value})
                new[field] = value
        if new["likelihood"] not in scores:
            raise CalculationError(f"records.xlsx row {row_no} ({r['id']}): likelihood must be one of {scores}.")
        if not 0 <= new["impact_min"] <= new["impact_likely"] <= new["impact_max"]:
            raise CalculationError(f"records.xlsx row {row_no} ({r['id']}): impacts must be in order: "
                                   "minimum <= most likely <= maximum, and not negative.")
        kept.append(new)
    return kept, changes


def run_calculation(run_folder: Path, settings: dict, base_value: float | None, client=None,
                    merge: bool | None = None, progress=print, already_spent_usd: float = 0.0) -> dict:
    """already_spent_usd: what this run has spent so far (from extraction, when
    run by 'review'), so that the per-run cap covers the whole run."""
    run_folder = Path(run_folder).resolve()
    extraction = load_extraction(run_folder)
    try:
        pack = load_pack(extraction["pack"])
    except ConfigError as e:
        raise CalculationError(str(e))
    SimulationSettings.from_settings(settings)  # check the settings before spending anything

    records, edits = apply_excel_edits(extraction["records"], run_folder / "records.xlsx", pack.config)
    if edits:
        progress(f"Using {len(edits)} change(s) made in records.xlsx.")

    calc_id, out_dir = create_run_folder(run_folder, Path("calculation"))
    ledger = Ledger(resolve_path(settings["budget"]["ledger_file"]))
    guard = CostGuard(settings["budget"]["per_run_cap_usd"], settings["pricing"])
    guard.spent_usd = already_spent_usd
    merge = settings.get("merging", {}).get("enabled", True) if merge is None else merge
    if merge and len(records) >= 2:
        if client is None:
            from risk_engine.pipeline import make_client
            client = make_client(settings)
        progress(f"Asking Claude ({settings['models']['classification']}) which of the {len(records)} "
                 "records are duplicates...")
        try:
            merged = merge_duplicates(records, pack.config, settings, client, guard, ledger, extraction["run_id"])
        except ExtractionStopped as e:
            raise CalculationError(f"Duplicate merging stopped: {e} You can add --no-merge to calculate "
                                   "without merging.")
    else:
        merged = no_merge(records)

    result = calculate(merged["records"], pack.config, settings, base_value)
    audit = {
        "calculation_id": calc_id,
        "extraction_run_id": extraction["run_id"],
        "pack": pack.name,
        "base_value": base_value,
        "base_value_label": pack.config.get("impact_basis", {}).get("base_value_label", "Base value"),
        "currency": pack.config.get("impact_basis", {}).get("currency", ""),
        "excel_edits": edits,
        "merging": {k: v for k, v in merged.items() if k != "records"},
        "records_before_merging": len(records),
        "records_after_merging": len(merged["records"]),
        "result": result,
        "scales": {k: pack.config[k] for k in ("likelihood_scale", "impact_scale", "rating")},
        "simulation_settings": settings.get("simulation", {}),
        "models": {"classification": settings["models"]["classification"]},
        "cost_usd": round(guard.spent_usd - already_spent_usd, 6),
        "software": {"engine_version": __version__, "python": platform.python_version()},
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(out_dir / "calculation_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, default=str)
    from risk_engine.calc_report import write_calculation_workbook
    write_calculation_workbook(audit, pack.config, out_dir / "risk_calculation.xlsx")
    return {"out_dir": str(out_dir), "audit": audit, "audit_file": str(out_dir / "calculation_audit.json"),
            "workbook": str(out_dir / "risk_calculation.xlsx")}
