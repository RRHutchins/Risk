"""Stages 5 and 6 run: from a calculation, find opportunities, write the
narrative, and produce the Word report, Excel register and run audit file."""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from risk_engine import __version__
from risk_engine.calc_pipeline import CalculationError
from risk_engine.config import resolve_path
from risk_engine.costs import CostGuard, Ledger
from risk_engine.extract import ExtractionStopped
from risk_engine.opportunity import assess, find_opportunities
from risk_engine.packs import load_pack
from risk_engine.report import write_register_workbook, write_report
from risk_engine.synthesise import decision_indicator, figures


def run_report(calc_folder: Path, settings: dict, client=None, use_claude: bool = True,
               already_spent_usd: float = 0.0, progress=print) -> dict:
    calc_folder = Path(calc_folder).resolve()
    calc_file = calc_folder / "calculation_audit.json"
    if not calc_file.exists():
        raise CalculationError(f"No calculation results in {calc_folder}. Give the folder that the "
                               "'calculate' command created (inside the run folder).")
    calculation = json.loads(calc_file.read_text(encoding="utf-8"))
    extraction = json.loads((calc_folder.parent / "extraction_audit.json").read_text(encoding="utf-8"))
    pack = load_pack(calculation["pack"])
    calc = calculation["result"]
    base = calc.get("base_value")

    ledger = Ledger(resolve_path(settings["budget"]["ledger_file"]))
    guard = CostGuard(settings["budget"]["per_run_cap_usd"], settings["pricing"])
    guard.spent_usd = already_spent_usd
    run_id = extraction["run_id"]

    if use_claude:
        if client is None:
            from risk_engine.pipeline import make_client
            client = make_client(settings)
        try:
            progress(f"Looking for mitigations and opportunities ({settings['models'].get('opportunity', settings['models']['classification'])})...")
            opp = find_opportunities(calc["records"], pack, settings, base, client, guard, ledger, run_id)
            progress(f"Writing the summary ({settings['models']['synthesis']})...")
            from risk_engine.synthesise import synthesise
            syn = synthesise(calc, opp, extraction["checklist"], pack, settings, client, guard, ledger, run_id)
        except ExtractionStopped as e:
            raise CalculationError(f"The report step stopped: {e} You can add --no-claude to write the report "
                                   "without the opportunity finder and written summary.")
    else:
        opp = {**assess({}, calc["records"], pack.config, base), "status": "skipped",
               "message": "switched off for this run", "cost_usd": 0.0}
        syn = {"indicator": decision_indicator(calc, extraction["checklist"], pack.config),
               "figures": figures(calc, opp, extraction["checklist"], pack.currency),
               "narrative": None, "status": "skipped", "message": "switched off for this run", "cost_usd": 0.0}

    project = Path(extraction["folder"]).name
    bundle = {
        "project_name": project,
        "pack": pack.name,
        "extraction": extraction,
        "calculation": calculation,
        "opportunity": opp,
        "synthesis": syn,
        "models": {"extraction": extraction.get("models", {}).get("extraction"),
                   "merging": (calculation.get("models", {}).get("classification")
                               if calculation["merging"].get("note") != "duplicate merging switched off" else None),
                   "opportunity finder": opp.get("model"), "synthesis": syn.get("model")},
        "cost_usd": round(extraction["summary"]["actual_usd"] + calculation.get("cost_usd", 0)
                          + opp.get("cost_usd", 0) + syn.get("cost_usd", 0), 6),
        "software": {"engine_version": __version__, "python": platform.python_version()},
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    stamp = datetime.now().strftime("%Y-%m-%d %H%M")
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in project)[:50].strip()
    report_path = calc_folder / f"Risk report - {safe} - {stamp}.docx"
    register_path = calc_folder / f"Risk register - {safe} - {stamp}.xlsx"
    audit_path = calc_folder / f"run_audit - {stamp}.json"
    write_report(bundle, pack, report_path, calc_folder)
    write_register_workbook(bundle, pack, register_path)
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, default=str)
    return {"report": str(report_path), "register": str(register_path), "audit": str(audit_path),
            "bundle": bundle}
